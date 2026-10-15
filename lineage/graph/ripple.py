"""Change propagates along lineage.

1. company_ripple: inside lineage:company, the changed PEP and its text go stale;
   PEPs that cite/require it (≤ depth hops) are flagged as relying on it.
2. agent_fanout: Cypher cannot cross graphs, so the stale ids are sent to each
   agent's memory graph, where Evidence stubs carry the same ids. Walking
   DERIVED_FROM upward finds every belief/answer/action built on them.
"""

from lineage.db import ro, rw
from lineage.graph import queries as Q
from lineage.graph.tools import _fragment

_SOFT = {1: Q.RIPPLE_SOFT_1, 2: Q.RIPPLE_SOFT_2, 3: Q.RIPPLE_SOFT_3}


async def company_ripple(g, changed_ids: list[str], reason: str, depth: int = 1) -> dict:
    changed = sorted(set(changed_ids))
    superseders = [r["id"] for r in await ro(g, Q.SUPERSEDERS, {"changed": changed})]
    soft = sorted(r["id"] for r in await ro(g, _SOFT[max(1, min(depth, 3))], {"changed": changed, "exclude": superseders}))
    await rw(g, Q.MARK_PEPS_STALE, {"ids": changed, "reason": reason})
    if soft:
        await rw(g, Q.MARK_PEPS_STALE, {"ids": soft, "reason": f"cites {', '.join(changed)} ({reason})"})
    chunks = sorted(r["id"] for r in await rw(g, Q.MARK_CHUNKS_STALE, {"ids": changed, "reason": reason}))
    ids = changed + soft + superseders
    paths = _fragment(await ro(g, Q.RIPPLE_EDGES, {"ids": ids}))
    return {"hard": changed, "soft": soft, "superseders": sorted(superseders), "chunks": chunks, "paths": paths}


async def agent_fanout(ag, stale_refs: list[str], reason: str) -> dict:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    deps = await rw(ag, Q.DEPENDENTS_OF_EVIDENCE, {"refs": sorted(set(stale_refs)), "reason": reason})
    by = {"Belief": [], "Answer": [], "Action": []}
    for d in deps:
        by[d["label"]].append(d["id"])
    if by["Belief"]:
        await rw(ag, Q.MARK_BELIEFS_STALE, {"ids": by["Belief"], "reason": reason, "now": now})
    if by["Answer"]:
        await rw(ag, Q.MARK_ANSWERS_STALE, {"ids": by["Answer"], "reason": reason, "now": now})
    blocked = []
    if by["Action"]:
        blocked = [r["id"] for r in await rw(ag, Q.BLOCK_ACTIONS, {"ids": by["Action"], "reason": f"stale lineage: {reason}"})]
    return {"beliefs": sorted(by["Belief"]), "answers": sorted(by["Answer"]), "actions_blocked": sorted(blocked)}


async def clear_stale(g) -> None:
    await rw(g, Q.CLEAR_STALE)
