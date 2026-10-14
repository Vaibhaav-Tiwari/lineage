"""Thin helpers over the async FalkorDB client.

Each graph is its own Redis key, so isolation between the company graph,
agent memories, user memories and forks is enforced by the database.
"""

from falkordb.asyncio import FalkorDB

from lineage.config import settings


async def get_db(user: str | None = None, password: str | None = None) -> FalkorDB:
    s = settings()
    return FalkorDB(
        host=s.falkor_host,
        port=s.falkor_port,
        username=user,
        password=password if user else s.falkor_password,
    )


def _column(h) -> str:
    # header entries come back as [type, name] pairs
    return h[1] if isinstance(h, (list, tuple)) else h


def _rows(result) -> list[dict]:
    cols = [_column(h) for h in result.header]
    return [dict(zip(cols, r)) for r in result.result_set]


async def ro(g, cypher: str, params: dict | None = None) -> list[dict]:
    """Read-only query (GRAPH.RO_QUERY) returning dict rows. Read-only agents
    can only use this command on the shared company graph (ACL selector)."""
    return _rows(await g.ro_query(cypher, params or {}))


async def rw(g, cypher: str, params: dict | None = None) -> list[dict]:
    return _rows(await g.query(cypher, params or {}))


async def write_batch(g, cypher: str, rows: list[dict], chunk: int = 500) -> int:
    """Run an `UNWIND $rows AS r ...` write in chunks. FalkorDB serialises
    writes per graph, so fewer, bigger writes are much faster than many small ones."""
    for i in range(0, len(rows), chunk):
        await g.query(cypher, {"rows": rows[i : i + chunk]})
    return len(rows)


async def create_acl_user(db: FalkorDB, name: str, password: str, own_pattern: str, read_patterns: list[str]) -> None:
    """Full access to graphs matching own_pattern; GRAPH.RO_QUERY only on read_patterns.

    Uses a Redis 7 ACL *selector* per read pattern. FalkorDB's documented
    `%R~pattern` form does not work on 6.0.2: every graph command needs RW key
    access, so `%R~` refuses even reads (verified 2026-10-14)."""
    rules = ["on", f">{password}", "resetkeys", "-@all", f"~{own_pattern}", "+@all"]
    rules += [f"(~{p} +GRAPH.RO_QUERY)" for p in read_patterns]
    await db.connection.execute_command("ACL", "SETUSER", name, *rules)


async def drop_acl_user(db: FalkorDB, name: str) -> None:
    await db.connection.execute_command("ACL", "DELUSER", name)
