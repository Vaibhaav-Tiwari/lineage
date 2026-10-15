from lineage.db import ro, rw
from lineage.graph.ripple import agent_fanout, clear_stale, company_ripple
from lineage.memory.store import propose_action, record_answer
from lineage.schema import ensure_agent_schema, ensure_company_schema

COMPANY = """
CREATE (p101:PEP {id:'pep:101', number:101, title:'Old'}), (p102:PEP {id:'pep:102', number:102, title:'New'}),
       (p103:PEP {id:'pep:103', number:103}), (p104:PEP {id:'pep:104', number:104}), (p105:PEP {id:'pep:105', number:105}),
       (p102)-[:SUPERSEDES]->(p101), (p103)-[:REFERENCES]->(p101), (p104)-[:REFERENCES]->(p103),
       (p102)-[:REFERENCES]->(p101), (p105)-[:REQUIRES]->(p104),
       (:Chunk {id:'c1'})-[:PART_OF]->(p101), (:Chunk {id:'c2'})-[:PART_OF]->(p101), (:Chunk {id:'c3'})-[:PART_OF]->(p103)
"""


async def _company(g):
    await ensure_company_schema(g)
    await rw(g, COMPANY)


async def test_ripple_hard_soft_and_chunks(g):
    await _company(g)
    r = await company_ripple(g, ["pep:101"], "PEP 101 superseded by PEP 102")
    assert r["hard"] == ["pep:101"]
    assert r["soft"] == ["pep:103", "pep:104"]  # 105 is 3 hops away; 102 is the superseder
    assert r["chunks"] == ["c1", "c2"]
    out = await ro(g, "MATCH (n) WHERE n.stale = true RETURN n.id AS id ORDER BY id")
    assert [x["id"] for x in out] == ["c1", "c2", "pep:101", "pep:103", "pep:104"]
    why = await ro(g, "MATCH (p:PEP {id:'pep:104'}) RETURN p.stale_because AS w")
    assert "pep:101" in why[0]["w"]
    assert {e["type"] for e in r["paths"].edges} >= {"REFERENCES", "SUPERSEDES"}


async def test_ripple_terminates_on_cycles_and_is_idempotent(g):
    await _company(g)
    await rw(g, "MATCH (a:PEP {id:'pep:101'}), (b:PEP {id:'pep:104'}) CREATE (a)-[:REFERENCES]->(b)")
    first = await company_ripple(g, ["pep:101"], "r")
    second = await company_ripple(g, ["pep:101"], "r")
    assert (first["hard"], first["soft"], first["chunks"]) == (second["hard"], second["soft"], second["chunks"])
    assert await ro(g, "MATCH (p:PEP {id:'pep:103'}) RETURN p.stale_because AS w") == [{"w": "cites pep:101 (r)"}]


async def test_clear_stale_resets(g):
    await _company(g)
    await company_ripple(g, ["pep:101"], "r")
    await clear_stale(g)
    assert await ro(g, "MATCH (n) WHERE n.stale = true RETURN count(n) AS c") == [{"c": 0}]


async def test_agent_fanout_marks_only_what_depends_on_changed_evidence(g):
    await ensure_agent_schema(g)
    a = await record_answer(g, "q", "a", ["pep:101"], [{"text": "B", "evidence": ["pep:101"], "confidence": 0.9}], None)
    x = await propose_action(g, "add_to_faq", {}, [a])
    other = await record_answer(g, "q2", "a2", ["pep:200"], [{"text": "C", "evidence": ["pep:200"], "confidence": 0.9}], None)
    r = await agent_fanout(g, ["pep:101"], "PEP 101 superseded")
    assert r["answers"] == [a] and len(r["beliefs"]) == 1 and r["actions_blocked"] == [x]
    assert await ro(g, "MATCH (b:Belief {text:'B'}) RETURN b.status AS s") == [{"s": "stale"}]
    assert await ro(g, "MATCH (b:Belief {text:'C'}) RETURN b.status AS s") == [{"s": "committed"}]
    assert await ro(g, "MATCH (a:Answer {id:$id}) RETURN a.stale AS s", {"id": other}) == [{"s": False}]
    assert await ro(g, "MATCH (x:Action {id:$id}) RETURN x.status AS s", {"id": x}) == [{"s": "blocked"}]
