from datetime import date

from lineage.db import ro
from lineage.memory.store import (
    explain_interest,
    forget_episode,
    list_beliefs,
    propose_action,
    record_answer,
    record_episode,
)
from lineage.schema import ensure_agent_schema, ensure_user_schema


async def test_record_answer_builds_lineage(g):
    await ensure_agent_schema(g)
    aid = await record_answer(g, "Why?", "Because.", ["pep:649", "person:gpshead"],
                              [{"text": "649 replaced 563", "evidence": ["pep:649"], "confidence": 0.9}], as_of=None)
    assert aid.startswith("answer:")
    assert await ro(g, "MATCH (e:Evidence) RETURN count(e) AS c") == [{"c": 2}]
    out = await ro(g, "MATCH (a:Answer {id:$id})-[:DERIVED_FROM]->(x) RETURN count(x) AS c", {"id": aid})
    assert out == [{"c": 3}]  # 2 evidence + 1 belief
    beliefs = await list_beliefs(g)
    assert len(beliefs) == 1 and beliefs[0]["status"] == "committed"
    chain = await ro(g, "MATCH (:Belief)-[:DERIVED_FROM]->(e:Evidence) RETURN e.ref AS r")
    assert chain == [{"r": "pep:649"}]


async def test_evidence_stubs_deduped_by_ref(g):
    await ensure_agent_schema(g)
    await record_answer(g, "q1", "a1", ["pep:649", "person:gpshead"], [], as_of=None)
    await record_answer(g, "q2", "a2", ["pep:649", "pep:563"], [], as_of=date(2024, 1, 1))
    assert await ro(g, "MATCH (e:Evidence) RETURN count(e) AS c") == [{"c": 3}]


async def test_low_confidence_belief_is_tentative(g):
    await ensure_agent_schema(g)
    await record_answer(g, "q", "a", ["pep:1"], [{"text": "maybe", "evidence": ["pep:1"], "confidence": 0.5}], as_of=None)
    assert [b["status"] for b in await list_beliefs(g)] == ["tentative"]
    assert await list_beliefs(g, status="committed") == []


async def test_propose_action_is_pending_and_linked(g):
    await ensure_agent_schema(g)
    aid = await record_answer(g, "q", "a", ["pep:1"], [], as_of=None)
    act = await propose_action(g, "add_to_faq", {"title": "x"}, derived_from=[aid])
    out = await ro(g, "MATCH (x:Action {id:$id})-[:DERIVED_FROM]->(a:Answer) RETURN x.status AS s, a.id AS a", {"id": act})
    assert out == [{"s": "pending", "a": aid}]


async def test_user_memory_weights_explain_and_provable_forget(g):
    await ensure_user_schema(g)
    e1 = await record_episode(g, "What is PEP 484?", "answer:1", ["area:typing"])
    e2 = await record_episode(g, "And PEP 649?", "answer:2", ["area:typing", "area:annotationlib"])
    assert await ro(g, "MATCH (i:Interest {area_ref:'area:typing'}) RETURN i.weight AS w") == [{"w": 2}]
    f = await explain_interest(g, "area:typing")
    assert {e1, e2} <= f.ids()
    await forget_episode(g, e1)
    assert await ro(g, "MATCH (i:Interest {area_ref:'area:typing'}) RETURN i.weight AS w") == [{"w": 1}]
    assert e1 not in (await explain_interest(g, "area:typing")).ids()
    await forget_episode(g, e2)
    assert await ro(g, "MATCH (i:Interest) RETURN count(i) AS c") == [{"c": 0}]
    assert await ro(g, "MATCH (e:Episode) RETURN count(e) AS c") == [{"c": 0}]
