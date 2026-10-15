"""MCP server: use the company brain from Claude Desktop / Claude Code.

    uv run python -m lineage.mcp_server        # stdio transport

All tools are read-only on the company graph except `ask`, which writes the
Historian's memory (that's how its answers can later go stale).
"""

import json
import os
from datetime import date

from mcp.server.mcpserver import MCPServer

from lineage.db import get_db
from lineage.graph.ownership import ownership_drift as _drift
from lineage.graph.tools import decision_path as _decision_path
from lineage.graph.tools import who_knows as _who_knows
from lineage.graph.whatif import departure_impact as _departure

PREFIX = os.environ.get("LINEAGE_PREFIX", "lineage")
mcp = MCPServer("lineage")
_embedder = None


def _dump(x) -> str:
    return json.dumps(x, default=str)


@mcp.tool()
async def decision_path(pep: int) -> str:
    """Who proposed, decided, announced and implemented a PEP, and what it supersedes. Returns the evidence subgraph."""
    db = await get_db()
    try:
        f = await _decision_path(db.select_graph(f"{PREFIX}:company"), pep)
        return _dump({"summary": f.meta.get("summary"), **f.to_json()})
    finally:
        await db.aclose()


@mcp.tool()
async def who_knows(topic: str) -> str:
    """People for a Python area/module: listed experts (declared) vs people actually committing (revealed)."""
    db = await get_db()
    try:
        f = await _who_knows(db.select_graph(f"{PREFIX}:company"), topic)
        return _dump({"area": f.meta.get("area"), "experts": f.meta.get("experts", [])})
    finally:
        await db.aclose()


@mcp.tool()
async def ownership_drift() -> str:
    """Per module: listed-but-quiet owners, active-but-unlisted contributors, orphaned modules."""
    db = await get_db()
    try:
        return _dump(await _drift(db.select_graph(f"{PREFIX}:company")))
    finally:
        await db.aclose()


@mcp.tool()
async def departure_impact(person_id: str) -> str:
    """What breaks if this person (e.g. 'person:gvanrossum') left — computed on a GRAPH.COPY fork."""
    db = await get_db()
    try:
        return _dump(await _departure(db, person_id, base=f"{PREFIX}:company"))
    finally:
        await db.aclose()


@mcp.tool()
async def ask(question: str, as_of: str | None = None) -> str:
    """Ask the Historian a why/who/when question about the Python project; the answer cites graph ids."""
    global _embedder
    from lineage.agents.backends import make_llm
    from lineage.agents.historian import ask as _ask
    from lineage.ingest.embed import Embedder
    from lineage.schema import ensure_agent_schema

    _embedder = _embedder or Embedder()
    db = await get_db()
    try:
        ag = db.select_graph(f"{PREFIX}:agent:historian")
        await ensure_agent_schema(ag)
        r = await _ask(question, company_g=db.select_graph(f"{PREFIX}:company"), agent_g=ag, user_g=None,
                       llm=make_llm(), embedder=_embedder, as_of=date.fromisoformat(as_of) if as_of else None)
        return _dump({k: v for k, v in r.to_json().items() if k != "evidence"})
    finally:
        await db.aclose()


if __name__ == "__main__":
    mcp.run()
