from lineage.graph.udf import ensure_udfs


async def test_udfs_are_only_reloaded_when_their_code_changed(db):
    # replacing a JavaScript library while queries use it crashed FalkorDB 6.0.2 (QuickJS assertion), so
    # an unchanged library must be left alone
    await ensure_udfs(db)
    assert await ensure_udfs(db) == "unchanged"
