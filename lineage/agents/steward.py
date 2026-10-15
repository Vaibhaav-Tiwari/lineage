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
    report["faq_withdrawn"] = 0
    if shared_g is not None:
        from lineage.memory.coord import open_fix_tasks_for
        from lineage.memory.effects import withdraw_faq

        report["fixtasks"] = await open_fix_tasks_for(shared_g, company_g, ripple, reason, event=slug)
        stale_answers = sorted({a for r in results for a in r.get("answers", [])})
        report["faq_withdrawn"] = await withdraw_faq(shared_g, stale_answers, reason, slug)
    from lineage.graph.plain import explain_ripple

    report["plain"] = explain_ripple(report)
    return report


async def reset_event(company_g, agent_graphs, slug: str, shared_g=None) -> None:
    """Undo a change event everywhere: company graph, every agent's memory, the shared board."""
    from lineage.db import rw
    from lineage.graph import queries as Q
    from lineage.memory.coord import delete_tasks_of_event

    await rewind_event(company_g, slug)
    await clear_stale(company_g)
    for ag in agent_graphs:
        await rw(ag, Q.RESTORE_BELIEFS)
        await rw(ag, Q.RESTORE_ACTIONS)
        await clear_stale(ag)
    if shared_g is not None:
        await delete_tasks_of_event(shared_g, slug)
        await rw(shared_g, Q.RESTORE_FAQ, {"event": slug})
