import pytest

from lineage.db import ro, rw
from lineage.graph.plain import explain_preview
from lineage.graph.whatif import departure_impact, preview_reversal, search_people, search_peps
from lineage.schema import ensure_agent_schema, ensure_company_schema

from tests.test_whatif import FIX

PEOPLE = """
CREATE (:Person {id:'person:vstinner', name:'Victor Stinner', github:'vstinner'}),
       (:Person {id:'person:vsajip', name:'Vinay Sajip', github:'vsajip'}),
       (:Person {id:'person:jevnik', name:'Joseph Jevnik', github:'llllllllll'}),
       (:Person {id:'person:sobolevn', github:'sobolevn'})
"""


async def test_people_search_ranks_prefix_matches_first_from_one_character(g):
    await ensure_company_schema(g)
    await rw(g, PEOPLE)
    names = [p["name"] for p in await search_people(g, "v")]
    assert names[:2] == ["Victor Stinner", "Vinay Sajip"] or names[:2] == ["Vinay Sajip", "Victor Stinner"]
    assert [p["id"] for p in await search_people(g, "vn")][0] == "person:sobolevn" or \
           "person:jevnik" in [p["id"] for p in await search_people(g, "vn")]
    first = (await search_people(g, "jos"))[0]
    assert first["id"] == "person:jevnik" and first["handle"] == "llllllllll"
    assert await search_people(g, "") == []


async def test_group_departure_removes_everyone_in_one_fork(db, g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    w = await departure_impact(db, ["person:erin", "person:a"], base=g.name)
    assert set(w["orphaned_areas"]) == {"xml"} and w["people_count"] == 2
    assert w["plain"]["headline"].startswith("If erin and a left, Python would")
    assert not [n for n in await db.list_graphs() if ":fork:" in n and n.startswith(g.name)]
    with pytest.raises(ValueError):
        await departure_impact(db, ["person:erin", "person:ghost"], base=g.name)


async def test_preview_reversal_counts_dependents_without_changing_anything(db, g):
    await ensure_company_schema(g)
    await rw(g, """CREATE (p:PEP {id:'pep:484', number:484, title:'Type Hints', status:'Final', pagerank:0.5}),
                          (a:PEP {id:'pep:585', number:585, title:'Generics', pagerank:0.2})-[:REFERENCES]->(p),
                          (b:PEP {id:'pep:604', number:604, title:'Unions', pagerank:0.1})-[:REQUIRES]->(p),
                          (:Chunk {id:'c1'})-[:PART_OF]->(p)""")
    agent = db.select_graph(g.name + ":agent:historian")
    try:
        await ensure_agent_schema(agent)
        from lineage.memory.store import propose_action, record_answer

        ans = await record_answer(agent, "q", "a", ["pep:484"], [{"text": "b", "evidence": ["pep:484"], "confidence": 0.9}], None)
        await propose_action(agent, "faq", {}, [ans])
        r = await preview_reversal(g, 484, agent_graphs={"historian": agent})
        assert r["pep"]["title"] == "Type Hints" and [p["id"] for p in r["dependents"]] == ["pep:585", "pep:604"]
        assert r["agents"]["historian"] == {"answers": 1, "beliefs": 1, "actions": 1}
        # nothing changed
        assert await ro(g, "MATCH (n) WHERE n.stale = true RETURN count(n) AS c") == [{"c": 0}]
        assert await ro(agent, "MATCH (b:Belief) RETURN b.status AS s") == [{"s": "committed"}]
        assert "nothing has been changed" in r["plain"].lower() and "2 other proposals" in r["plain"]
    finally:
        await agent.delete()


async def test_pep_search_by_number_or_title(g):
    await ensure_company_schema(g)
    await rw(g, "CREATE (:PEP {id:'pep:484', number:484, title:'Type Hints', pagerank:0.5}), (:PEP {id:'pep:48', number:48, title:'Other', pagerank:0.1})")
    assert [p["number"] for p in await search_peps(g, "484")] == [484]
    assert [p["number"] for p in await search_peps(g, "type")] == [484]


def test_preview_plain_when_nothing_depends():
    s = explain_preview({"pep": {"number": 1, "title": "X"}, "dependents": [], "agents": {"historian": {"answers": 0, "beliefs": 0, "actions": 0}}})
    assert "no other proposal cites it" in s.lower() and "nothing has been changed" in s.lower()


async def test_preview_reversal_explains_each_dependent_and_draws_a_graph(db, g):
    await ensure_company_schema(g)
    await rw(g, """CREATE (p:PEP {id:'pep:484', number:484, title:'Type Hints', status:'Final', pagerank:0.5}),
                          (a:PEP {id:'pep:585', number:585, title:'Generics', status:'Final', created: date('2019-03-03'), pagerank:0.2})-[:REFERENCES]->(p),
                          (b:PEP {id:'pep:604', number:604, title:'Unions', status:'Final', created: date('2019-08-28'), pagerank:0.1})-[:REQUIRES]->(p)""")
    agent = db.select_graph(g.name + ":agent:historian")
    try:
        await ensure_agent_schema(agent)
        from lineage.memory.store import record_answer

        ans = await record_answer(agent, "q", "Type hints came from PEP 484.", ["pep:484"], [], None)
        r = await preview_reversal(g, 484, agent_graphs={"historian": agent})
        rows = {d["id"]: d for d in r["dependents"]}
        assert rows["pep:585"]["relation"] == "cites" and rows["pep:604"]["relation"] == "requires"
        assert rows["pep:585"]["created"] == "2019-03-03"
        would = {n["id"]: n["props"].get("would") for n in r["fragment"]["nodes"]}
        assert would == {"pep:484": "reverse", "pep:585": "review", "pep:604": "review", ans: "review"}
        edges = {(e["src"], e["type"], e["dst"]) for e in r["fragment"]["edges"]}
        assert ("pep:585", "REFERENCES", "pep:484") in edges and (ans, "DERIVED_FROM", "pep:484") in edges
    finally:
        await agent.delete()
