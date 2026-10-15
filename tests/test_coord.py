import asyncio

import pytest

from lineage.db import ro, rw
from lineage.memory.coord import claim_next, complete, list_tasks, open_fix_tasks, open_fix_tasks_for
from lineage.schema import ensure_company_schema, ensure_shared_schema

ITEMS = [{"kind": "review", "target_ref": f"pep:{i}", "reason": "r"} for i in range(10)]


async def test_open_is_idempotent(g):
    await ensure_shared_schema(g)
    a = await open_fix_tasks(g, ITEMS)
    b = await open_fix_tasks(g, ITEMS)
    assert a == b and len(a) == 10
    assert len(await list_tasks(g)) == 10


async def test_concurrent_claims_never_double_claim(g):
    await ensure_shared_schema(g)
    await open_fix_tasks(g, ITEMS)
    results = await asyncio.gather(*[claim_next(g, f"worker-{i % 2}") for i in range(20)])
    claimed = [r["id"] for r in results if r]
    assert len(claimed) == 10 and len(set(claimed)) == 10
    assert sum(r is None for r in results) == 10


async def test_expired_claim_can_be_reclaimed(g):
    await ensure_shared_schema(g)
    await open_fix_tasks(g, ITEMS[:1])
    first = await claim_next(g, "worker-a", ttl_s=0)
    second = await claim_next(g, "worker-b")
    assert first["id"] == second["id"] == "fix:review:pep:0"
    assert (await list_tasks(g, "claimed"))[0]["claimed_by"] == "worker-b"


async def test_only_the_claimer_can_complete(g):
    await ensure_shared_schema(g)
    await open_fix_tasks(g, ITEMS[:1])
    t = await claim_next(g, "worker-a")
    with pytest.raises(PermissionError):
        await complete(g, t["id"], "worker-b")
    await complete(g, t["id"], "worker-a")
    assert (await list_tasks(g, "done"))[0]["id"] == t["id"]


async def test_fix_tasks_from_ripple_suggest_area_owners(db):
    import uuid

    cg, sg = db.select_graph(f"test:{uuid.uuid4().hex[:8]}"), db.select_graph(f"test:{uuid.uuid4().hex[:8]}")
    try:
        await ensure_company_schema(cg)
        await ensure_shared_schema(sg)
        await rw(cg, """CREATE (p:PEP {id:'pep:103', number:103, title:'Uses old'})-[:CONCERNS]->(a:Area {id:'area:typing', name:'typing'}),
                        (:Person {id:'person:alice', github:'alice'})-[:EXPERT_IN {inactive:false}]->(a),
                        (:Person {id:'person:zed', github:'zed'})-[:EXPERT_IN {inactive:true}]->(a)""")
        ripple = {"hard": ["pep:101"], "soft": ["pep:103"]}
        ids = await open_fix_tasks_for(sg, cg, ripple, "101 superseded")
        assert ids == ["fix:review-citation:pep:103"]
        t = (await list_tasks(sg))[0]
        assert t["suggested"] == ["alice"] and "pep:101" in t["reason"]
    finally:
        await cg.delete()
        await sg.delete()
