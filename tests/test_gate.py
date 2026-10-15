import pytest

from lineage.db import ro
from lineage.graph.ripple import agent_fanout
from lineage.memory.gate import ActionBlocked, check_action, execute_action
from lineage.memory.store import propose_action, record_answer
from lineage.schema import ensure_agent_schema


async def test_stale_lineage_blocks_with_path(g):
    await ensure_agent_schema(g)
    a = await record_answer(g, "q", "a", ["pep:101"], [{"text": "B", "evidence": ["pep:101"], "confidence": 0.9}], None)
    x = await propose_action(g, "add_to_faq", {}, [a])
    await agent_fanout(g, ["pep:101"], "superseded")
    c = await check_action(g, x)
    assert c["allowed"] is False and "pep:101" in c["reason"] and "stale" in c["reason"]
    assert x in c["path"] and "ev:pep:101" in c["path"]


async def test_clean_lineage_is_allowed_and_executes_once(g):
    await ensure_agent_schema(g)
    a = await record_answer(g, "q", "a", ["pep:200"], [{"text": "C", "evidence": ["pep:200"], "confidence": 0.9}], None)
    x = await propose_action(g, "add_to_faq", {"title": "t"}, [a])
    assert (await check_action(g, x))["allowed"] is True
    out = await execute_action(g, x)
    assert out["status"] == "done"
    assert await ro(g, "MATCH (o:Outbox) RETURN count(o) AS c") == [{"c": 1}]


async def test_tentative_belief_blocks(g):
    await ensure_agent_schema(g)
    a = await record_answer(g, "q", "a", ["pep:300"], [{"text": "maybe", "evidence": ["pep:300"], "confidence": 0.4}], None)
    x = await propose_action(g, "add_to_faq", {}, [a])
    c = await check_action(g, x)
    assert c["allowed"] is False and "tentative" in c["reason"]


async def test_execute_blocked_raises_and_writes_nothing(g):
    await ensure_agent_schema(g)
    a = await record_answer(g, "q", "a", ["pep:101"], [], None)
    x = await propose_action(g, "add_to_faq", {}, [a])
    await agent_fanout(g, ["pep:101"], "superseded")
    with pytest.raises(ActionBlocked):
        await execute_action(g, x)
    assert await ro(g, "MATCH (o:Outbox) RETURN count(o) AS c") == [{"c": 0}]
