from lineage.db import rw
from lineage.graph.ownership import ownership_drift
from lineage.schema import ensure_company_schema

FIX = """
CREATE (arg:Area {id:'area:argparse', name:'argparse'}), (xml:Area {id:'area:xml', name:'xml'}),
       (ok:Area {id:'area:json', name:'json'}),
       (alice:Person {id:'person:alice', github:'alice'}), (bob:Person {id:'person:bob', github:'bob'}),
       (dave:Person {id:'person:dave', github:'dave'}), (carol:Person {id:'person:carol', github:'carol'}),
       (erin:Person {id:'person:erin', github:'erin'}),
       (alice)-[:EXPERT_IN {inactive:false}]->(arg), (alice)-[:COMMITTED_TO {count:5, last_at:date('2026-05-01')}]->(arg),
       (bob)-[:EXPERT_IN {inactive:false}]->(arg),
       (dave)-[:COMMITTED_TO {count:4, last_at:date('2026-06-01')}]->(arg),
       (carol)-[:EXPERT_IN {inactive:true}]->(xml),
       (erin)-[:EXPERT_IN {inactive:false}]->(ok), (erin)-[:COMMITTED_TO {count:9, last_at:date('2026-07-01')}]->(ok)
"""


async def test_drift_statuses(g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    out = await ownership_drift(g, areas=["area:argparse", "area:xml", "area:json"])
    by = {r["area"]: r for r in out}
    assert by["argparse"]["listed_but_quiet"] == ["bob"]
    assert by["argparse"]["active_but_unlisted"] == ["dave"]
    assert by["argparse"]["status"] == "drifting"
    assert by["xml"]["status"] == "orphaned"
    assert by["json"]["status"] == "healthy"
    assert [r["area"] for r in out] == sorted(r["area"] for r in out)  # by area, never a ranking of people


async def test_default_scope_is_areas_with_commit_data(g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    assert {r["area"] for r in await ownership_drift(g)} == {"argparse", "json"}
