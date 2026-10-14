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

from lineage.agents.historian import ask
from lineage.db import create_acl_user, drop_acl_user, get_db
from lineage.memory.store import explain_interest, forget_episode, list_beliefs, list_interests
from lineage.schema import ensure_agent_schema, ensure_user_schema

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
        from lineage.agents.llm import AnthropicLLM

        return AnthropicLLM()

    async def user_graph(self, uid: str, db=None):
        g = (db or self.db).select_graph(self.name("user", uid))
        if uid not in self._user_schemas:
            await ensure_user_schema(self.db.select_graph(self.name("user", uid)))
            self._user_schemas.add(uid)
        return g

    async def shutdown(self):
        if self.ready:
            await drop_acl_user(self.db, self.hist_user)
            await self.historian_db.aclose()
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

    return app


app = create_app()
