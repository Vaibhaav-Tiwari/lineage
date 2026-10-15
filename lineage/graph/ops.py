"""Observability for the demo: graphs, memory per graph, slow queries."""


def _pairs(raw) -> dict:
    it = list(raw or [])
    return {(k.decode() if isinstance(k, bytes) else k): v for k, v in zip(it[0::2], it[1::2])}


async def graph_mb(db, name: str) -> float:
    raw = await db.connection.execute_command("GRAPH.MEMORY", "USAGE", name)
    return float(_pairs(raw).get("total_graph_sz_mb", 0) or 0)


async def graph_stats(db) -> list[dict]:
    return [{"graph": n, "mb": await graph_mb(db, n)} for n in sorted(await db.list_graphs())]


async def slowlog(db, name: str, n: int = 3) -> list:
    rows = await db.connection.execute_command("GRAPH.SLOWLOG", name)
    out = [{"at": r[0], "command": r[1], "query": r[2], "ms": float(r[3])} for r in rows or []]
    return sorted(out, key=lambda r: -r["ms"])[:n]
