"""The Steward: applies change events and makes every agent un-learn.

apply_event: event → company ripple → fan-out to every agent graph (in
parallel: separate graphs, separate write queues) → actions blocked.
reset_event: puts the demo back to "before the event" (rewind + clear stale).
"""

import asyncio

from lineage.graph.ripple import agent_fanout, clear_stale, company_ripple
from lineage.ingest.events import _spec, mark_event_applied, rewind_event


async def apply_event(slug: str, *, company_g, agent_graphs: dict, shared_g=None) -> dict:
    e = await _spec(company_g, slug)
    changed = await mark_event_applied(company_g, slug)
    reason = e.summary or f"{slug} applied"
    ripple = await company_ripple(company_g, changed, reason)
    stale_refs = ripple["hard"] + ripple["soft"] + ripple["chunks"]
    names = list(agent_graphs)
    results = await asyncio.gather(*(agent_fanout(agent_graphs[n], stale_refs, reason) for n in names))
    report = {
        "event": slug, "summary": e.summary, "changed": changed,
        "ripple": {k: ripple[k] for k in ("hard", "soft", "superseders", "chunks")},
        "paths": ripple["paths"].to_json(),
        "agents": dict(zip(names, results)),
        "fixtasks": [],
    }
    if shared_g is not None:
        from lineage.memory.coord import open_fix_tasks_for

        report["fixtasks"] = await open_fix_tasks_for(shared_g, company_g, ripple, reason)
    return report


async def reset_event(company_g, agent_graphs, slug: str) -> None:
    await rewind_event(company_g, slug)
    await clear_stale(company_g)
    for ag in agent_graphs:
        await clear_stale(ag)
