from lineage.db import rw
from lineage.graph.clusters import pep_clusters
from lineage.graph.tools import TOOL_SPECS, connection
from lineage.graph.whatif import departure_impact
from lineage.schema import ensure_company_schema

from tests.test_tools import FIXTURE


async def test_connection_finds_shortest_chain_between_names_and_peps(g):
    await ensure_company_schema(g)
    await rw(g, FIXTURE)
    f = await connection(g, "Dan", "PEP 101")
    assert f.meta["path"] == ["person:dan", "pep:102", "pep:101"]
    assert [e["type"] for e in f.edges] == ["AUTHORED", "SUPERSEDES"]
    assert "Dan" in f.meta["summary"] and "supersedes" in f.meta["summary"].lower()


async def test_connection_unknown_or_unconnected_says_so(g):
    await ensure_company_schema(g)
    await rw(g, FIXTURE)
    assert "not found" in (await connection(g, "Nobody Atall", "PEP 101")).meta["summary"]
    await rw(g, "CREATE (:PEP {id:'pep:999', number:999, title:'Island'})")
    assert "no connection" in (await connection(g, "PEP 999", "PEP 101")).meta["summary"].lower()


def test_connection_is_an_agent_tool():
    assert "connection" in {t["name"] for t in TOOL_SPECS}


async def test_pep_clusters_label_by_most_influential_member(g):
    await ensure_company_schema(g)
    await rw(g, """
    CREATE (a:PEP {id:'pep:1', number:1, title:'Core A', pagerank:0.9}), (b:PEP {id:'pep:2', number:2, title:'A two', pagerank:0.1}),
           (c:PEP {id:'pep:3', number:3, title:'A three', pagerank:0.2}),
           (x:PEP {id:'pep:10', number:10, title:'Core X', pagerank:0.8}), (y:PEP {id:'pep:11', number:11, title:'X two', pagerank:0.1}),
           (z:PEP {id:'pep:12', number:12, title:'X three', pagerank:0.1}),
           (b)-[:REFERENCES]->(a), (c)-[:REFERENCES]->(a), (c)-[:REFERENCES]->(b),
           (y)-[:REFERENCES]->(x), (z)-[:REFERENCES]->(x), (z)-[:REFERENCES]->(y)
    """)
    clusters = await pep_clusters(g, min_size=3)
    assert sorted(c["label"] for c in clusters) == ["Core A", "Core X"]
    assert all(c["size"] == 3 for c in clusters)


async def test_whatif_reports_bridge_score(db, g):
    from tests.test_whatif import FIX

    from lineage.ingest.derive import materialize_ties

    await ensure_company_schema(g)
    await rw(g, FIX)
    await materialize_ties(g)  # betweenness needs undirected (two-way) ties
    w = await departure_impact(db, "person:erin", base=g.name)
    assert w["bridge_rank"] == 1 and w["bridge_score"] > 0 and w["people_ranked"] >= 4
