"""HTTP API for the web UI (and anything else).

Graph layout (prefix defaults to "lineage"):
  <prefix>:company           shared company brain (written only by ingest/Steward)
  <prefix>:agent:historian   the Historian's memory
  <prefix>:user:<uid>        one memory graph per user
The Historian runs on its own FalkorDB login: RO_QUERY-only on the company
graph, full access to its own memory and user graphs (database-enforced).
"""

import asyncio
import re
import secrets
from datetime import date
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

import json

from lineage.agents.historian import ask
from lineage.agents.steward import apply_event, reset_event
from lineage.db import create_acl_user, drop_acl_user, get_db, ro
from lineage.graph import queries as Q
from lineage.graph.ops import graph_stats, slowlog
from lineage.graph.ownership import ownership_drift
from lineage.graph.whatif import departure_impact
from lineage.memory import coord
from lineage.memory.gate import ActionBlocked, execute_action
from lineage.memory.store import explain_interest, forget_episode, list_beliefs, list_interests, propose_action
from lineage.schema import ensure_agent_schema, ensure_shared_schema, ensure_user_schema

UID = re.compile(r"^[a-z0-9-]{1,32}$")
AGENTS = ("historian",)


class AskBody(BaseModel):
    question: str
    user_id: str | None = None
    as_of: date | None = None

    @field_validator("user_id")
    @classmethod
    def _uid(cls, v):
        if v is not None and not UID.match(v):
            raise ValueError("user_id must match ^[a-z0-9-]{1,32}$")
        return v


class ActionBody(BaseModel):
    kind: str
    payload: dict = {}
    derived_from: list[str]


class AgentBody(BaseModel):
    agent: str


class WhatIfBody(BaseModel):
    person_id: str


class State:
    def __init__(self, prefix: str, llm_factory: Callable | None, embedder):
        self.prefix, self._llm_factory, self._embedder = prefix, llm_factory, embedder
        self._lock = asyncio.Lock()
        self.ready = False
        self._user_schemas: set[str] = set()

    def name(self, *parts: str) -> str:
        return ":".join((self.prefix, *parts))

    async def init(self):
        async with self._lock:
            if self.ready:
                return
            self.db = await get_db()
            for a in AGENTS:
                await ensure_agent_schema(self.db.select_graph(self.name("agent", a)))
            # ACL users live in memory only, so (re)create them on every start
            self.hist_user, pw = f"{self.prefix}_historian", secrets.token_urlsafe(24)
            await create_acl_user(self.db, self.hist_user, pw,
                                  own_pattern=[self.name("agent", "historian"), self.name("user", "*")],
                                  read_patterns=[self.name("company")])
            self.historian_db = await get_db(user=self.hist_user, password=pw)
            await ensure_shared_schema(self.db.select_graph(self.name("shared")))
            self.stew_user, spw = f"{self.prefix}_steward", secrets.token_urlsafe(24)
            await create_acl_user(self.db, self.stew_user, spw,
                                  own_pattern=[self.name("company") + "*", self.name("agent", "*"), self.name("shared")],
                                  read_patterns=[])
            self.steward_db = await get_db(user=self.stew_user, password=spw)
            if self._embedder is None:
                from lineage.ingest.embed import Embedder

                self._embedder = Embedder()
            self.ready = True

    @property
    def embedder(self):
        return self._embedder

    def llm(self):
        if self._llm_factory:
            return self._llm_factory()
        from lineage.agents.backends import make_llm

        return make_llm()

    async def user_graph(self, uid: str, db=None):
        g = (db or self.db).select_graph(self.name("user", uid))
        if uid not in self._user_schemas:
            await ensure_user_schema(self.db.select_graph(self.name("user", uid)))
            self._user_schemas.add(uid)
        return g

    async def shutdown(self):
        if self.ready:
            await drop_acl_user(self.db, self.hist_user)
            await drop_acl_user(self.db, self.stew_user)
            await self.historian_db.aclose()
            await self.steward_db.aclose()
            await self.db.aclose()
            self.ready = False


def create_app(prefix: str = "lineage", llm_factory: Callable | None = None, embedder=None,
               cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="Lineage", description="A company brain that un-learns.")
    st = State(prefix, llm_factory, embedder)
    app.state.st = st
    app.state.shutdown = st.shutdown
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins or ["*"], allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def _ensure_ready(request: Request, call_next):
        await st.init()
        app.state.historian_db = st.historian_db
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"falkordb": "ok", "graphs": sorted(await st.db.list_graphs())}

    @app.post("/ask")
    async def ask_(body: AskBody):
        hdb = st.historian_db
        user_g = await st.user_graph(body.user_id, hdb) if body.user_id else None
        r = await ask(body.question, company_g=hdb.select_graph(st.name("company")),
                      agent_g=hdb.select_graph(st.name("agent", "historian")), user_g=user_g,
                      llm=st.llm(), embedder=st.embedder, as_of=body.as_of)
        return r.to_json()

    @app.get("/beliefs")
    async def beliefs(agent: str = "historian", status: str | None = None):
        if agent not in AGENTS:
            raise HTTPException(404, "unknown agent")
        return await list_beliefs(st.db.select_graph(st.name("agent", agent)), status)

    def _uid(uid: str) -> str:
        if not UID.match(uid):
            raise HTTPException(422, "bad user id")
        return uid

    @app.get("/users/{uid}/interests")
    async def interests(uid: str):
        return await list_interests(await st.user_graph(_uid(uid)))

    @app.get("/users/{uid}/interests/{area}/why")
    async def why(uid: str, area: str):
        return (await explain_interest(await st.user_graph(_uid(uid)), area)).to_json()

    @app.delete("/users/{uid}/episodes/{eid}")
    async def forget(uid: str, eid: str):
        await forget_episode(await st.user_graph(_uid(uid)), eid)
        return {"forgotten": eid}

    # --- Steward: events, ripple, gate ------------------------------------------------

    def agent_graphs(db):
        return {a: db.select_graph(st.name("agent", a)) for a in AGENTS}

    @app.get("/events")
    async def events():
        rows = await ro(st.db.select_graph(st.name("company")), Q.LIST_EVENTS)
        return [{**{k: v for k, v in r.items() if k != "payload"}, "slug": r["id"].split(":", 1)[1],
                 "by": json.loads(r["payload"] or "{}").get("by", [])} for r in rows]

    @app.post("/events/{slug}/apply")
    async def apply(slug: str):
        sdb = st.steward_db
        return await apply_event(slug, company_g=sdb.select_graph(st.name("company")),
                                 agent_graphs=agent_graphs(sdb), shared_g=sdb.select_graph(st.name("shared")))

    @app.post("/events/{slug}/rewind")
    async def rewind(slug: str):
        sdb = st.steward_db
        await reset_event(sdb.select_graph(st.name("company")), list(agent_graphs(sdb).values()), slug)
        return {"rewound": slug}

    @app.post("/actions")
    async def new_action(body: ActionBody):
        ag = st.historian_db.select_graph(st.name("agent", "historian"))
        return {"id": await propose_action(ag, body.kind, body.payload, body.derived_from)}

    @app.get("/actions")
    async def actions():
        return await ro(st.db.select_graph(st.name("agent", "historian")), Q.LIST_ACTIONS)

    @app.post("/actions/{aid}/execute")
    async def run_action(aid: str):
        try:
            return await execute_action(st.historian_db.select_graph(st.name("agent", "historian")), aid)
        except ActionBlocked as e:
            raise HTTPException(409, {"reason": e.reason, "path": e.path})

    # --- Shared coordination board ------------------------------------------------------

    @app.get("/fixtasks")
    async def fixtasks(status: str | None = None):
        return await coord.list_tasks(st.db.select_graph(st.name("shared")), status)

    @app.post("/fixtasks/claim")
    async def claim(body: AgentBody):
        return await coord.claim_next(st.steward_db.select_graph(st.name("shared")), body.agent)

    @app.post("/fixtasks/{tid}/complete")
    async def done(tid: str, body: AgentBody):
        try:
            await coord.complete(st.steward_db.select_graph(st.name("shared")), tid, body.agent)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        return {"done": tid}

    # --- Org: ownership drift + what-if ------------------------------------------------

    @app.get("/org/drift")
    async def drift():
        return await ownership_drift(st.db.select_graph(st.name("company")))

    @app.get("/org/people")
    async def people(q: str = ""):
        return await ro(st.db.select_graph(st.name("company")), Q.SEARCH_PEOPLE, {"q": q})

    @app.post("/org/whatif")
    async def whatif(body: WhatIfBody):
        try:
            return await departure_impact(st.steward_db, body.person_id, base=st.name("company"))
        except ValueError as e:
            raise HTTPException(404, str(e))

    # --- Index card --------------------------------------------------------------------

    LABELS = {"pep": "PEP", "person": "Person", "decision": "Decision", "thread": "Thread", "post": "Post",
              "pr": "PR", "chunk": "Chunk", "area": "Area", "event": "Event", "team": "Team"}

    @app.get("/nodes/{nid:path}")
    async def node_card(nid: str):
        label = LABELS.get(nid.split(":", 1)[0])
        if not label:
            raise HTTPException(404, "unknown id")
        rows = await ro(st.db.select_graph(st.name("company")), Q.CARD_BY_LABEL[label], {"id": nid})
        if not rows:
            raise HTTPException(404, "not found")
        from lineage.graph.tools import _clean

        props = _clean(rows[0]["props"])
        if "text" in props and isinstance(props["text"], str):
            props["text"] = props["text"][:800]
        neighbours = [{"rel": r["rel"], "direction": "out" if r["outgoing"] else "in", "id": r["mid"],
                       "label": r["ml"], "name": r["mname"]} for r in rows if r["rel"]]
        beliefs = await ro(st.db.select_graph(st.name("agent", "historian")), Q.BELIEFS_ON_REF, {"ref": nid})
        return {"id": nid, "label": label, "props": props, "neighbours": neighbours, "beliefs": beliefs}

    # --- Ops + demo reset ----------------------------------------------------------------

    @app.get("/ops/graphs")
    async def ops_graphs():
        return [g for g in await graph_stats(st.db) if g["graph"].startswith(st.prefix + ":")]

    @app.get("/ops/slowlog")
    async def ops_slowlog(graph: str = "company"):
        return await slowlog(st.db, st.name(graph))

    @app.post("/demo/reset")
    async def demo_reset():
        """Back to 'before the event': rewind replay events, clear stale flags,
        wipe agent memories and the shared board (company data is untouched)."""
        for g in [*agent_graphs(st.db).values(), st.db.select_graph(st.name("shared"))]:
            if g.name in await st.db.list_graphs():
                await g.delete()
        for a in AGENTS:
            await ensure_agent_schema(st.db.select_graph(st.name("agent", a)))
        await ensure_shared_schema(st.db.select_graph(st.name("shared")))
        company = st.db.select_graph(st.name("company"))
        for e in await events():
            await reset_event(company, [], e["slug"])
        return {"reset": True}

    return app


app = create_app()
