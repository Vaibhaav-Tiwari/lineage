import json
import uuid

from lineage import mcp_server
from lineage.db import get_db, rw
from lineage.schema import ensure_company_schema

from tests.test_tools import FIXTURE


async def test_mcp_tools_query_the_graph(monkeypatch):
    prefix = f"test{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(mcp_server, "PREFIX", prefix)
    db = await get_db()
    cg = db.select_graph(f"{prefix}:company")
    try:
        await ensure_company_schema(cg)
        await rw(cg, FIXTURE)
        out = json.loads(await mcp_server.decision_path(102))
        assert "pep:101" in {n["id"] for n in out["nodes"]} and "Bob" in out["summary"]
        who = json.loads(await mcp_server.who_knows("argparse"))
        assert {e["id"] for e in who["experts"]} == {"person:alice", "person:dave"}
        assert {t.name for t in await mcp_server.mcp.list_tools()} == {
            "ask", "decision_path", "who_knows", "ownership_drift", "departure_impact"}
    finally:
        for n in await db.list_graphs():
            if n.startswith(prefix):
                await db.select_graph(n).delete()
        await db.aclose()
