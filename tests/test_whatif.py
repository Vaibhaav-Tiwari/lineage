import pytest

from lineage.db import rw
from lineage.graph.ops import graph_stats
from lineage.graph.whatif import departure_impact
from lineage.schema import ensure_company_schema

FIX = """
CREATE (xml:Area {id:'area:xml', name:'xml'}), (js:Area {id:'area:json', name:'json'}),
       (erin:Person {id:'person:erin', github:'erin'}), (a:Person {id:'person:a', github:'a'}), (b:Person {id:'person:b', github:'b'}),
       (c:Person {id:'person:c', github:'c'}), (d:Person {id:'person:d', github:'d'}),
       (erin)-[:EXPERT_IN {inactive:false}]->(xml), (erin)-[:COMMITTED_TO {count:6}]->(xml),
       (a)-[:EXPERT_IN {inactive:false}]->(js), (b)-[:COMMITTED_TO {count:4}]->(js),
       (a)-[:COLLABORATED {weight:3}]->(b), (c)-[:COLLABORATED {weight:2}]->(d),
       (a)-[:COLLABORATED {weight:5}]->(erin), (erin)-[:COLLABORATED {weight:1}]->(c),
       (erin)-[:AUTHORED]->(:PEP {id:'pep:1', number:1})
"""


async def test_departure_orphans_area_splits_network_and_cleans_up(db, g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    w = await departure_impact(db, "person:erin", base=g.name)
    assert w["orphaned_areas"] == ["xml"]
    assert w["components_before"] == 1 and w["components_after"] == 2
    assert "a" in w["suggested_successors"]["xml"]  # erin's strongest collaborator
    assert w["successor_basis"]["xml"] == "collaboration"  # nobody else commits to xml
    assert w["plain"]["headline"].startswith("If erin left, Python would")
    assert w["authored_peps"] == 1 and w["fork_mb"] >= 0
    # the live graph still has erin, and no fork is left behind
    assert (await g.ro_query("MATCH (p:Person {id:'person:erin'}) RETURN count(p)")).result_set == [[1]]
    assert not [n for n in await db.list_graphs() if ":fork:" in n and n.startswith(g.name)]


async def test_unknown_person_raises_before_copying(db, g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    with pytest.raises(ValueError):
        await departure_impact(db, "person:nobody", base=g.name)
    assert not [n for n in await db.list_graphs() if n.startswith(g.name + ":fork")]


async def test_graph_stats_reports_memory(db, g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    stats = {s["graph"]: s for s in await graph_stats(db)}
    assert g.name in stats and stats[g.name]["mb"] >= 0
