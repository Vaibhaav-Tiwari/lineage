import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from lineage.agents.llm import FakeLLM, LLMTurn
from lineage.api.main import create_app
from lineage.db import get_db, rw
from lineage.schema import ensure_company_schema

from tests.test_tools import FIXTURE


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


def _script():
    return [
        LLMTurn("", [{"id": "a", "name": "decision_path", "input": {"pep": 102}}], "tool_use"),
        LLMTurn("", [{"id": "b", "name": "submit_answer", "input": {
            "text": "Bob announced it.", "citations": ["pep:102", "person:bob"],
            "beliefs": [{"text": "Bob announced 102", "evidence": ["person:bob"], "confidence": 0.9}]}}], "tool_use"),
    ]


@pytest.fixture
async def app_env():
    prefix = f"test{uuid.uuid4().hex[:6]}"
    db = await get_db()
    cg = db.select_graph(f"{prefix}:company")
    await ensure_company_schema(cg)
    await rw(cg, FIXTURE)
    await rw(cg, "MATCH (p:PEP {id:'pep:102'}) CREATE (p)-[:CONCERNS]->(:Area {id:'area:typing', name:'typing'})")
    app = create_app(prefix=prefix, llm_factory=lambda: FakeLLM(_script()), embedder=FakeEmbedder())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, prefix, db
    await app.state.shutdown()
    for name in await db.list_graphs():
        if name.startswith(prefix + ":"):
            await db.select_graph(name).delete()
    await db.aclose()


async def test_health_lists_company_graph(app_env):
    c, prefix, _ = app_env
    r = await c.get("/health")
    assert r.status_code == 200 and r.json()["falkordb"] == "ok"
    assert f"{prefix}:company" in r.json()["graphs"]


async def test_ask_returns_answer_and_evidence(app_env):
    c, _, _ = app_env
    r = await c.post("/ask", json={"question": "Who announced PEP 102?"})
    assert r.status_code == 200
    body = r.json()
    assert body["citations"] == ["pep:102", "person:bob"] and not body["abstained"]
    assert {n["id"] for n in body["evidence"]["nodes"]} >= {"pep:102", "person:bob"}
    beliefs = (await c.get("/beliefs", params={"agent": "historian"})).json()
    assert [b["status"] for b in beliefs] == ["committed"]


async def test_bad_user_id_is_rejected(app_env):
    c, _, _ = app_env
    r = await c.post("/ask", json={"question": "q", "user_id": "Bad Id!"})
    assert r.status_code == 422


async def test_user_memory_roundtrip_and_forget(app_env):
    c, _, _ = app_env
    await c.post("/ask", json={"question": "Who announced PEP 102?", "user_id": "u1"})
    interests = (await c.get("/users/u1/interests")).json()
    assert [i["area"] for i in interests] == ["area:typing"]
    why = (await c.get("/users/u1/interests/area:typing/why")).json()
    eid = next(n["id"] for n in why["nodes"] if n["label"] == "Episode")
    assert (await c.delete(f"/users/u1/episodes/{eid}")).status_code == 200
    assert (await c.get("/users/u1/interests")).json() == []


async def test_historian_connection_cannot_write_company_graph(app_env):
    c, prefix, _ = app_env
    await c.get("/health")  # app initialises lazily on first request
    hist = c._transport.app.state.historian_db
    with pytest.raises(Exception, match="(?i)noperm|permission"):
        await hist.select_graph(f"{prefix}:company").query("CREATE (:Hack)")
