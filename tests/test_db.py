import uuid

import pytest

from lineage.db import create_acl_user, drop_acl_user, get_db, ro, write_batch

MERGE_X = "UNWIND $rows AS r MERGE (:X {id: r.id})"


async def test_write_batch_idempotent(g):
    rows = [{"id": "x:1"}, {"id": "x:2"}]
    assert await write_batch(g, MERGE_X, rows) == 2
    await write_batch(g, MERGE_X, rows)
    out = await ro(g, "MATCH (n:X) RETURN count(n) AS c")
    assert out == [{"c": 2}]


async def test_write_batch_chunks_large_input(g):
    rows = [{"id": f"x:{i}"} for i in range(1203)]
    assert await write_batch(g, MERGE_X, rows, chunk=500) == 1203
    assert (await ro(g, "MATCH (n:X) RETURN count(n) AS c"))[0]["c"] == 1203


async def test_graph_isolation(db):
    a = db.select_graph(f"test:{uuid.uuid4().hex[:8]}")
    b = db.select_graph(f"test:{uuid.uuid4().hex[:8]}")
    try:
        await a.query("CREATE (:X {id:'only-in-a'})")
        await b.query("CREATE (:Y)")  # make b exist
        out = await ro(b, "MATCH (n:X) RETURN count(n) AS c")
        assert out == [{"c": 0}]
    finally:
        await a.delete()
        await b.delete()


async def test_acl_read_only_shared_graph(db):
    tag = uuid.uuid4().hex[:6]
    shared = db.select_graph(f"test:shared{tag}")
    own_name = f"test:own{tag}"
    await shared.query("CREATE (:X {v:1})")
    user, pw = f"t_hist_{tag}", "pw-" + tag
    await create_acl_user(db, user, pw, own_pattern=f"test:own{tag}*", read_patterns=[f"test:shared{tag}*"])
    agent = await get_db(user=user, password=pw)
    try:
        # reading the shared graph works
        assert await ro(agent.select_graph(f"test:shared{tag}"), "MATCH (n) RETURN count(n) AS c") == [{"c": 1}]
        # writing the shared graph is refused by the database
        with pytest.raises(Exception, match="(?i)noperm|permission"):
            await agent.select_graph(f"test:shared{tag}").query("CREATE (:X {v:2})")
        # writing its own graph works
        await agent.select_graph(own_name).query("CREATE (:Mine)")
        assert (await ro(db.select_graph(own_name), "MATCH (n:Mine) RETURN count(n) AS c")) == [{"c": 1}]
    finally:
        await agent.aclose()
        await drop_acl_user(db, user)
        await shared.delete()
        await db.select_graph(own_name).delete()
