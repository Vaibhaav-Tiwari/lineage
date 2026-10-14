import uuid

import pytest

from lineage.db import get_db


@pytest.fixture
async def db():
    conn = await get_db()
    yield conn
    await conn.aclose()


@pytest.fixture
async def g(db):
    """A fresh, uniquely named graph per test — deleted afterwards."""
    name = f"test:{uuid.uuid4().hex[:8]}"
    graph = db.select_graph(name)
    yield graph
    if name in await db.list_graphs():
        await graph.delete()
