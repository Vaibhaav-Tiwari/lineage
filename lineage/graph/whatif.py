"""What if this person left?

FalkorDB's algorithm procedures (WCC, betweenness, ...) run over whole label /
relationship sets — they can't "skip one node". So we GRAPH.COPY the company
graph into a throwaway fork, delete the person there, re-run the algorithms,
compare, and delete the fork. The live graph is never touched.
"""

import time
import uuid

from lineage.db import ro, rw
from lineage.graph import queries as Q
from lineage.graph.ops import graph_mb


async def _components(g) -> int:
    return (await ro(g, Q.COLLAB_COMPONENTS))[0]["n"]


async def _active(g, areas: list[str]) -> dict[str, dict]:
    return {r["id"]: r for r in await ro(g, Q.ACTIVE_IN_AREAS, {"areas": areas})}


async def departure_impact(db, person_id: str, base: str = "lineage:company") -> dict:
    t0 = time.perf_counter()
    live = db.select_graph(base)
    found = await ro(live, Q.PERSON_EXISTS, {"id": person_id})
    if not found:
        raise ValueError(f"unknown person {person_id}")
    areas = [r["id"] for r in await ro(live, Q.AREAS_OF_PERSON, {"id": person_id})]
    before_active = await _active(live, areas)
    comps_before = await _components(live)
    footprint = (await ro(live, Q.PERSON_FOOTPRINT, {"id": person_id}))[0]
    collaborators = [r["who"] for r in await ro(live, Q.TOP_COLLABORATORS, {"id": person_id})]
    ranking = await ro(live, Q.BETWEENNESS_PEOPLE)
    rank = next((i + 1 for i, r in enumerate(ranking) if r["id"] == person_id), None)
    score = next((r["score"] for r in ranking if r["id"] == person_id), 0.0)

    fork_name = f"{base}:fork:{uuid.uuid4().hex[:8]}"
    await live.copy(fork_name)
    fork = db.select_graph(fork_name)
    try:
        fork_mb = await graph_mb(db, fork_name)
        await rw(fork, Q.DELETE_PERSON, {"id": person_id})
        comps_after = await _components(fork)
        after_active = await _active(fork, areas)
    finally:
        await fork.delete()

    orphaned, at_risk, successors = [], [], {}
    for aid, b in before_active.items():
        left = after_active.get(aid, {}).get("n", 0)
        if left == 0:
            orphaned.append(b["name"])
        elif left == 1:
            at_risk.append({"area": b["name"], "remaining": 1})
        if left <= 1:
            committers = [r["who"] for r in await ro(live, Q.AREA_COMMITTERS, {"area": aid, "id": person_id})]
            successors[b["name"]] = list(dict.fromkeys(committers + collaborators))[:3]
    return {
        "person": found[0], "fork": fork_name, "fork_mb": fork_mb,
        "orphaned_areas": sorted(orphaned), "at_risk_areas": sorted(at_risk, key=lambda x: x["area"]),
        "components_before": comps_before, "components_after": comps_after,
        "suggested_successors": successors, "authored_peps": footprint["authored"],
        "decisions_announced": footprint["announced"],
        "bridge_rank": rank, "bridge_score": round(float(score), 1), "people_ranked": len(ranking), "ms": round((time.perf_counter() - t0) * 1000),
    }
