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
    assert by["json"]["plain"] == "The listed owners are the people doing the work."
    assert [r["area"] for r in out] == sorted(r["area"] for r in out)  # by area, never a ranking of people


async def test_default_scope_is_areas_with_commit_data(g):
    await ensure_company_schema(g)
    await rw(g, FIX)
    assert {r["area"] for r in await ownership_drift(g)} == {"argparse", "json"}


HEALTH = """
CREATE (a:Area {id:'area:asyncio', name:'asyncio'}),
       (o:Person {id:'person:old', name:'Old Hand'}), (n:Person {id:'person:new', name:'New Hand'}), (b:Person {id:'person:bit', name:'Bit Part'}),
       (o)-[:WORKED_ON {dates:['2025-11-01','2025-11-02','2025-11-03','2025-11-04','2025-11-05','2025-11-06']}]->(a),
       (n)-[:WORKED_ON {dates:['2026-10-01','2026-10-02','2026-10-03']}]->(a),
       (b)-[:WORKED_ON {dates:['2026-01-01']}]->(a)
"""


async def test_recent_work_counts_more_and_gives_a_truck_factor(db, g):
    from datetime import date

    from lineage.graph.ownership import module_health
    from lineage.graph.udf import ensure_udfs

    await ensure_udfs(db)
    await rw(g, HEALTH)
    asy = (await module_health(g, as_of=date(2026, 10, 16)))[0]
    assert asy["area_id"] == "area:asyncio"
    assert [o["id"] for o in asy["owners"]] == ["person:new", "person:old", "person:bit"]  # 3 recent beat 6 a year old
    assert asy["truck_factor"] == 1 and 0.5 < asy["owners"][0]["share"] < 0.7


TIES = """
CREATE (x:Area {id:'area:x', name:'x'}),
       (a:Person {id:'person:a', name:'A'}), (b:Person {id:'person:b', name:'B'}), (c:Person {id:'person:c', name:'C'}),
       (d:Person {id:'person:d', name:'D'}),
       (c)-[:WORKED_ON {dates:['2026-10-01','2026-10-02','2026-10-03','2026-10-04']}]->(x),
       (a)-[:COLLABORATED {weight:5}]->(b), (b)-[:COLLABORATED {weight:5}]->(c),
       (a)-[:COLLABORATED {weight:1}]->(d), (d)-[:COLLABORATED {weight:1}]->(c)
"""


async def test_introduction_follows_the_strongest_working_ties_to_the_current_owner(db, g):
    from datetime import date

    from lineage.graph import queries as Q
    from lineage.graph.ownership import introduction
    from lineage.graph.udf import ensure_udfs

    await ensure_udfs(db)
    await rw(g, TIES)
    await rw(g, Q.MATERIALIZE_TIES)
    intro = await introduction(g, "person:a", "area:x", as_of=date(2026, 10, 16))
    assert intro["to"]["id"] == "person:c"
    assert [p["id"] for p in intro["path"]] == ["person:a", "person:b", "person:c"]  # strong ties, not the weak shortcut
    assert {e["type"] for e in intro["fragment"]["edges"]} == {"TIE", "WORKED_ON"}



async def test_module_health_can_be_asked_as_of_an_earlier_date(db, g):
    from datetime import date

    from lineage.graph.ownership import module_health
    from lineage.graph.udf import ensure_udfs

    await ensure_udfs(db)
    await rw(g, HEALTH)
    then = (await module_health(g, as_of=date(2025, 12, 1)))[0]
    assert [o["id"] for o in then["owners"]] == ["person:old"]  # nobody else had committed yet
    assert then["owners"][0]["commits"] == 6
