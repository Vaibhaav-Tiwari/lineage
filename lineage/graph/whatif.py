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


async def departure_impact(db, person_ids: str | list[str], base: str = "lineage:company") -> dict:
    """What if this person — or this group of people — left? Computed on one fork."""
    from lineage.graph.plain import explain_departure

    t0 = time.perf_counter()
    ids = [person_ids] if isinstance(person_ids, str) else list(dict.fromkeys(person_ids))
    live = db.select_graph(base)
    found = {r["id"]: r for r in await ro(live, Q.PERSONS_EXIST, {"ids": ids})}
    missing = [i for i in ids if i not in found]
    if missing or not ids:
        raise ValueError(f"unknown person {', '.join(missing) or '(none given)'}")
    areas = [r["id"] for r in await ro(live, Q.AREAS_OF_PEOPLE, {"ids": ids})]
    before_active = await _active(live, areas)
    comps_before = await _components(live)
    footprint = (await ro(live, Q.GROUP_FOOTPRINT, {"ids": ids}))[0]
    collab_rows = await ro(live, Q.TOP_COLLABORATORS_OF_GROUP, {"ids": ids})
    collaborators = [r["who"] for r in collab_rows]
    ranking = await ro(live, Q.BETWEENNESS_PEOPLE)
    ranks = [i + 1 for i, r in enumerate(ranking) if r["id"] in ids]
    rank = min(ranks) if ranks else None
    score = max((r["score"] for r in ranking if r["id"] in ids), default=0.0)

    fork_name = f"{base}:fork:{uuid.uuid4().hex[:8]}"
    await live.copy(fork_name)
    fork = db.select_graph(fork_name)
    try:
        fork_mb = await graph_mb(db, fork_name)
        await rw(fork, Q.DELETE_PEOPLE, {"ids": ids})
        comps_after = await _components(fork)
        after_active = await _active(fork, areas)
    finally:
        await fork.delete()

    orphaned, at_risk, successors, basis, affected = [], [], {}, {}, []
    for aid, b in before_active.items():
        left = after_active.get(aid, {}).get("n", 0)
        if left == 0:
            orphaned.append(b["name"])
        elif left == 1:
            at_risk.append({"area": b["name"], "remaining": 1})
        if left <= 1:
            commit_rows = await ro(live, Q.AREA_COMMITTERS_EXCEPT, {"area": aid, "ids": ids})
            committers = [r["who"] for r in commit_rows]
            successors[b["name"]] = list(dict.fromkeys(committers or collaborators))[:3]
            basis[b["name"]] = "commits" if committers else "collaboration"
            picks = [{"id": r["id"], "name": r["who"], "basis": "commits", "commits": r["n"]} for r in commit_rows] or \
                    [{"id": r["id"], "name": r["who"], "basis": "collaboration", "commits": None} for r in collab_rows]
            affected.append({"id": aid, "name": b["name"], "state": "orphaned" if left == 0 else "one_left", "successors": picks[:3]})
    names = [found[i]["name"] for i in ids]
    label = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    result = {
        "person": {"id": ids[0] if len(ids) == 1 else "group", "name": label}, "people": [found[i] for i in ids],
        "people_count": len(ids), "fork": fork_name, "fork_mb": fork_mb,
        "orphaned_areas": sorted(orphaned), "at_risk_areas": sorted(at_risk, key=lambda x: x["area"]),
        "components_before": comps_before, "components_after": comps_after,
        "suggested_successors": successors, "successor_basis": basis, "authored_peps": footprint["authored"],
        "decisions_announced": footprint["announced"],
        "bridge_rank": rank, "bridge_score": round(float(score), 1), "people_ranked": len(ranking),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
    result["areas"] = sorted(affected, key=lambda a: (a["state"] != "orphaned", a["name"]))
    result["fragment"] = await _departure_graph(live, result["people"], result["areas"])
    result["plain"] = explain_departure(result)
    return result


async def _departure_graph(g, people: list[dict], areas: list[dict]) -> dict:
    """What the departure would look like on the graph: who leaves, what they leave behind, who could step in."""
    nodes = {p["id"]: {"id": p["id"], "label": "Person", "props": {"name": p.get("name"), "would": "leave"}} for p in people}
    edges = []
    for a in areas:
        nodes[a["id"]] = {"id": a["id"], "label": "Area", "props": {"name": a["name"], "would": a["state"]}}
        for s in a["successors"]:
            nodes.setdefault(s["id"], {"id": s["id"], "label": "Person", "props": {"name": s["name"], "would": "step_in"}})
            edges.append({"src": s["id"], "dst": a["id"], "type": "STEP_IN"})
    links = await ro(g, Q.PEOPLE_AREA_LINKS, {"ids": [p["id"] for p in people], "areas": [a["id"] for a in areas]})
    edges += [{"src": r["p"], "dst": r["a"], "type": r["t"]} for r in links]
    return {"nodes": list(nodes.values()), "edges": edges}


async def preview_reversal(g, pep: int, agent_graphs: dict, depth: int = 1) -> dict:
    """What if this proposal were reversed? A dry run of the Steward's ripple:
    read-only queries on the live graphs — nothing is marked, nothing changes."""
    from lineage.graph.plain import explain_preview
    from lineage.graph.ripple import _SOFT

    pid = f"pep:{int(pep)}"
    found = await ro(g, Q.PEP_BRIEFS, {"ids": [pid]})
    if not found:
        raise ValueError(f"unknown proposal {pid}")
    soft = [r["id"] for r in await ro(g, _SOFT[max(1, min(depth, 3))], {"changed": [pid], "exclude": []})]
    dependents = await ro(g, Q.PEP_BRIEFS, {"ids": soft}) if soft else []
    chunks = [r["id"] for r in await ro(g, Q.CHUNKS_OF_PEPS, {"ids": [pid]})]
    refs = [pid] + soft + chunks
    agents = {}
    for name, ag in agent_graphs.items():
        counts = {r["label"]: r["n"] for r in await ro(ag, Q.DEPENDENTS_PREVIEW, {"refs": refs})}
        agents[name] = {"answers": counts.get("Answer", 0), "beliefs": counts.get("Belief", 0), "actions": counts.get("Action", 0)}
    rel = {r["id"]: r["rel"] for r in await ro(g, Q.DEPENDENT_RELATIONS, {"pid": pid, "ids": soft})} if soft else {}
    for d in dependents:
        d["relation"] = {"REQUIRES": "requires"}.get(rel.get(d["id"]), "cites")
    result = {"pep": found[0], "dependents": dependents, "agents": agents}
    result["plain"] = explain_preview(result)
    result["fragment"] = await _reversal_graph(g, pid, soft, refs, agent_graphs)
    return result


async def _reversal_graph(g, pid: str, soft: list[str], refs: list[str], agent_graphs: dict) -> dict:
    """The preview as a graph: the proposal that would be reversed, what would need review."""
    from lineage.graph.tools import _fragment

    frag = _fragment(await ro(g, Q.RIPPLE_EDGES, {"ids": [pid] + soft})).to_json()
    nodes = {n["id"]: n for n in frag["nodes"]}
    for i in [pid] + soft:  # proposals with no edge among themselves still belong on the graph
        nodes.setdefault(i, {"id": i, "label": "PEP", "props": {"number": int(i.split(":")[1])}})
    for i, n in nodes.items():
        n["props"] = {**n.get("props", {}), "stale": False, "would": "reverse" if i == pid else "review"}
    edges = list(frag["edges"])
    for ag in agent_graphs.values():
        for r in await ro(ag, Q.DEPENDENT_ANSWERS, {"refs": refs}):
            nodes.setdefault(r["id"], {"id": r["id"], "label": "Answer", "props": {"text": r["text"], "would": "review"}})
            edges.append({"src": r["id"], "dst": r["ref"] if r["ref"] in nodes else pid, "type": "DERIVED_FROM"})
    briefs = {b["id"]: b for b in await ro(g, Q.PEP_BRIEFS, {"ids": [pid] + soft})}
    for i, b in briefs.items():
        nodes[i]["props"].update({"title": b["title"], "status": b["status"], "created": b["created"]})
    return {"nodes": list(nodes.values()), "edges": list({(e["src"], e["type"], e["dst"]): e for e in edges}.values())}


async def search_people(g, q: str) -> list[dict]:
    if not q.strip():
        return []
    return await ro(g, Q.SEARCH_PEOPLE_RANKED, {"q": q.strip()})


async def search_peps(g, q: str) -> list[dict]:
    q = q.strip().lower().removeprefix("pep").strip()
    return await ro(g, Q.SEARCH_PEPS, {"q": q}) if q else []
