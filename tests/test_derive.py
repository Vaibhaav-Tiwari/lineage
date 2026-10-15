from lineage.db import ro, rw
from lineage.ingest.derive import compute_pagerank, derive_collaboration, derive_concerns
from lineage.schema import ensure_company_schema


async def test_collaboration_weights_sum_and_store_once(g):
    await ensure_company_schema(g)
    await rw(g, """
    CREATE (a:Person {id:'person:a'}), (b:Person {id:'person:b'}), (c:Person {id:'person:c'}),
           (p:PEP {id:'pep:1'}), (t1:Thread {id:'thread:1'}), (t2:Thread {id:'thread:2'}),
           (a)-[:AUTHORED]->(p), (b)-[:AUTHORED]->(p),
           (a)-[:POSTED]->(:Post {id:'post:1'})-[:IN]->(t1), (b)-[:POSTED]->(:Post {id:'post:2'})-[:IN]->(t1),
           (a)-[:POSTED]->(:Post {id:'post:3'})-[:IN]->(t2), (b)-[:POSTED]->(:Post {id:'post:4'})-[:IN]->(t2),
           (a)-[:POSTED]->(:Post {id:'post:5'})-[:IN]->(t2)
    """)
    await derive_collaboration(g)
    await derive_collaboration(g)  # idempotent
    out = await ro(g, "MATCH (x:Person)-[c:COLLABORATED]->(y:Person) RETURN x.id AS x, y.id AS y, c.weight AS w")
    assert out == [{"x": "person:a", "y": "person:b", "w": 5}]  # co-author 3 + two shared threads


async def test_concerns_from_title_or_repeated_mentions(g):
    await ensure_company_schema(g)
    await rw(g, """
    CREATE (:Area {id:'area:asyncio', name:'asyncio'}), (:Area {id:'area:enum', name:'enum'}), (:Area {id:'area:re', name:'re'}),
           (p1:PEP {id:'pep:1', title:'Async generators in asyncio'}),
           (p2:PEP {id:'pep:2', title:'Something else'}),
           (:Chunk {id:'c1', text:'The enum module gets enum members.'})-[:PART_OF]->(p2),
           (:Chunk {id:'c2', text:'A single enum mention.'})-[:PART_OF]->(p1),
           (:Chunk {id:'c3', text:'re re re re'})-[:PART_OF]->(p1)
    """)
    await derive_concerns(g)
    out = await ro(g, "MATCH (p:PEP)-[:CONCERNS]->(a:Area) RETURN p.id AS p, a.id AS a ORDER BY p, a")
    assert out == [{"p": "pep:1", "a": "area:asyncio"}, {"p": "pep:2", "a": "area:enum"}]  # short names like 're' ignored


async def test_pagerank_stored_on_peps(g):
    await ensure_company_schema(g)
    await rw(g, """
    CREATE (a:PEP {id:'pep:1'}), (b:PEP {id:'pep:2'}), (c:PEP {id:'pep:3'}), (d:PEP {id:'pep:4'}),
           (a)-[:REFERENCES]->(d), (b)-[:REFERENCES]->(d), (c)-[:REFERENCES]->(d), (a)-[:REFERENCES]->(b)
    """)
    await compute_pagerank(g)
    out = await ro(g, "MATCH (p:PEP) RETURN p.id AS id, p.pagerank AS pr ORDER BY pr DESC")
    assert all(isinstance(r["pr"], float) for r in out)
    assert out[0]["id"] == "pep:4"


async def test_generic_interest_areas_link_only_via_title(g):
    await ensure_company_schema(g)
    await rw(g, """
    CREATE (:Area {id:'area:performance', name:'performance', kind:'interest'}), (:Area {id:'area:typing', name:'typing', kind:'module'}),
           (p:PEP {id:'pep:1', title:'Annotations'}), (q:PEP {id:'pep:2', title:'Performance improvements'}),
           (:Chunk {id:'c1', text:'performance performance performance typing typing'})-[:PART_OF]->(p)
    """)
    await derive_concerns(g)
    out = await ro(g, "MATCH (p:PEP)-[:CONCERNS]->(a:Area) RETURN p.id AS p, a.id AS a ORDER BY p, a")
    assert out == [{"p": "pep:1", "a": "area:typing"}, {"p": "pep:2", "a": "area:performance"}]
