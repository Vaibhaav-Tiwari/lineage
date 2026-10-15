import json
import uuid
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from lineage.agents.llm import FakeLLM, LLMTurn
from lineage.api.main import create_app
from lineage.db import get_db
from lineage.ingest.events import load_events, upsert_events
from lineage.ingest.peps import load_peps, parse_peps
from lineage.schema import ensure_company_schema

FIX = Path(__file__).parent / "fixtures"


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


def _script():
    return [
        LLMTurn("", [{"id": "a", "name": "decision_path", "input": {"pep": 101}}], "tool_use"),
        LLMTurn("", [{"id": "b", "name": "submit_answer", "input": {
            "text": "PEP 101 is the current way.", "citations": ["pep:101"],
            "beliefs": [{"text": "101 is current", "evidence": ["pep:101"], "confidence": 0.9}]}}], "tool_use"),
    ]


@pytest.fixture
async def env(tmp_path):
    prefix = f"test{uuid.uuid4().hex[:6]}"
    db = await get_db()
    cg = db.select_graph(f"{prefix}:company")
    await ensure_company_schema(cg)
    await load_peps(cg, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
    cfg = tmp_path / "e.yaml"
    cfg.write_text(yaml.safe_dump([{"slug": "pep-101-superseded", "kind": "supersede", "at": "2021-07-07", "pep": 101,
                                    "by": [102, 105], "before_status": "Final", "after_status": "Superseded",
                                    "summary": "PEP 101 superseded by PEP 102", "replay": True}]))
    await upsert_events(cg, load_events(cfg))
    app = create_app(prefix=prefix, llm_factory=lambda: FakeLLM(_script()), embedder=FakeEmbedder())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, prefix
    await app.state.shutdown()
    for name in await db.list_graphs():
        if name.startswith(prefix + ":"):
            await db.select_graph(name).delete()
    await db.aclose()


async def test_full_demo_story_over_http(env):
    c, _ = env
    assert (await c.post("/events/pep-101-superseded/rewind")).status_code == 200
    events = (await c.get("/events")).json()
    assert events[0]["slug"] == "pep-101-superseded" and events[0]["applied"] is False

    ans = (await c.post("/ask", json={"question": "What is the current way?"})).json()
    a1 = (await c.post("/actions", json={"kind": "add_to_faq", "payload": {"q": "x"}, "derived_from": [ans["answer_id"]]})).json()
    assert (await c.post(f"/actions/{a1['id']}/execute")).status_code == 200
    a2 = (await c.post("/actions", json={"kind": "add_to_faq", "payload": {"q": "y"}, "derived_from": [ans["answer_id"]]})).json()

    rep = (await c.post("/events/pep-101-superseded/apply")).json()
    assert rep["changed"] == ["pep:101"] and "pep:103" in rep["ripple"]["soft"]
    assert rep["agents"]["historian"]["actions_blocked"] == [a2["id"]]
    assert rep["fixtasks"] == ["fix:review-citation:pep:103"]

    r = await c.post(f"/actions/{a2['id']}/execute")
    assert r.status_code == 409 and "pep:101" in r.json()["detail"]["reason"]
    assert (await c.get("/beliefs", params={"status": "stale"})).json()
    tasks = (await c.get("/fixtasks")).json()
    assert [t["status"] for t in tasks] == ["open"]
    claimed = (await c.post("/fixtasks/claim", json={"agent": "steward-1"})).json()
    assert claimed["id"] == tasks[0]["id"]
    assert (await c.post(f"/fixtasks/{claimed['id']}/complete", json={"agent": "steward-1"})).status_code == 200

    acts = {a["id"]: a["status"] for a in (await c.get("/actions")).json()}
    assert acts == {a1["id"]: "done", a2["id"]: "blocked"}


async def test_org_and_ops_endpoints(env):
    c, prefix = env
    assert (await c.get("/org/drift")).status_code == 200
    people = (await c.get("/org/people", params={"q": "ann"})).json()
    assert people and people[0]["id"] == "person:ann-author"
    w = (await c.post("/org/whatif", json={"person_id": "person:ann-author"})).json()
    assert w["authored_peps"] == 2
    assert (await c.post("/org/whatif", json={"person_id": "person:nobody"})).status_code == 404
    graphs = {g["graph"] for g in (await c.get("/ops/graphs")).json()}
    assert f"{prefix}:company" in graphs


async def test_steward_login_cannot_touch_user_memory(env):
    c, prefix = env
    await c.get("/health")
    st = c._transport.app.state.st
    with pytest.raises(Exception, match="(?i)noperm|permission"):
        await st.steward_db.select_graph(f"{prefix}:user:u1").query("CREATE (:X)")


async def test_demo_reset_wipes_agent_memory_and_rewinds(env):
    c, _ = env
    await c.post("/ask", json={"question": "q"})
    await c.post("/events/pep-101-superseded/apply")
    assert (await c.post("/demo/reset")).status_code == 200
    assert (await c.get("/beliefs")).json() == []
    assert (await c.get("/fixtasks")).json() == []
    assert (await c.get("/events")).json()[0]["applied"] is False


async def test_org_clusters_endpoint(env):
    c, _ = env
    r = await c.get("/org/clusters")
    assert r.status_code == 200 and isinstance(r.json(), list)
