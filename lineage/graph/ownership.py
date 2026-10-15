"""Declared vs revealed ownership, per area (never a ranking of people)."""

from collections import defaultdict
from datetime import date

from lineage.db import ro
from lineage.graph import queries as Q


async def ownership_drift(g, min_commits: int = 3, areas: list[str] | None = None) -> list[dict]:
    if areas is None:
        areas = [r["id"] for r in await ro(g, Q.TRACKED_AREAS)]
    names = {r["id"]: r["name"] for r in await ro(g, Q.AREA_NAMES, {"areas": areas})}
    declared, revealed = defaultdict(dict), defaultdict(dict)
    for r in await ro(g, Q.DRIFT_DECLARED, {"areas": areas}):
        declared[r["area_id"]][r["who"]] = r["inactive"]
    for r in await ro(g, Q.DRIFT_REVEALED, {"areas": areas}):
        last = r["last_at"].isoformat() if isinstance(r["last_at"], date) else r["last_at"]
        revealed[r["area_id"]][r["who"]] = {"commits": r["commits"], "last_at": last}
    out = []
    for aid in areas:
        d, rv = declared[aid], revealed[aid]
        active_declared = [w for w, inactive in d.items() if not inactive]
        committing = [w for w, x in rv.items() if x["commits"] >= min_commits]
        quiet = sorted(w for w in active_declared if w not in rv)
        unlisted = sorted(w for w in committing if w not in d)
        status = ("orphaned" if not committing and not active_declared
                  else "drifting" if quiet or unlisted else "healthy")
        out.append({
            "area": names.get(aid, aid.split(":", 1)[1]), "area_id": aid,
            "declared": sorted(d), "inactive": sorted(w for w, i in d.items() if i),
            "revealed": sorted(({"who": w, **x} for w, x in rv.items()), key=lambda x: x["who"]),
            "listed_but_quiet": quiet, "active_but_unlisted": unlisted, "status": status,
        })
    from lineage.graph.plain import explain_drift

    for r in out:
        r["plain"] = explain_drift(r)
    return sorted(out, key=lambda r: r["area"])


HALF_LIFE_DAYS = 180


def truck_factor(scores: list[float], cover: float = 0.5) -> int:
    """The fewest people who together hold at least `cover` of a module's recent knowledge."""
    total = sum(scores)
    if total <= 0:
        return 0
    run = 0.0
    for k, sc in enumerate(sorted(scores, reverse=True), 1):
        run += sc
        if run >= cover * total:
            return k
    return len(scores)


async def module_health(g, as_of: date | None = None, areas: list[str] | None = None) -> list[dict]:
    """Per module: who holds the recent knowledge (recency-weighted inside FalkorDB), and its truck factor."""
    from datetime import timedelta

    as_of = as_of or date.today()
    rows = await ro(g, Q.AREA_RECENCY, {"areas": areas, "as_of": as_of.isoformat(), "half_life": HALF_LIFE_DAYS,
                                        "since": (as_of - timedelta(days=365)).isoformat()})
    by: dict[str, dict] = {}
    for r in rows:
        if r["score"] <= 0:
            continue
        m = by.setdefault(r["area_id"], {"area_id": r["area_id"], "area": r["area"], "owners": []})
        m["owners"].append({"id": r["id"], "name": r["name"], "score": round(r["score"], 3), "commits": r["commits"]})
    for m in by.values():
        total = sum(o["score"] for o in m["owners"]) or 1.0
        m["owners"].sort(key=lambda o: -o["score"])
        for o in m["owners"]:
            o["share"] = round(o["score"] / total, 3)
        m["truck_factor"] = truck_factor([o["score"] for o in m["owners"]])
        m["owners"] = m["owners"][:5]
    return sorted(by.values(), key=lambda m: m["area"])


async def introduction(g, person_id: str, area_id: str, as_of: date | None = None) -> dict:
    """Who could introduce this person to whoever holds the most recent knowledge of a module, and through whom."""
    health = await module_health(g, as_of=as_of, areas=[area_id])
    owners = [o for o in (health[0]["owners"] if health else []) if o["id"] != person_id]
    if not owners:
        return {"to": None, "path": [], "area": area_id, "fragment": {"nodes": [], "edges": []}}
    to = owners[0]
    rows = await ro(g, Q.INTRO_PATH, {"src": person_id, "dst": to["id"]})
    if not rows:
        return {"to": to, "path": [], "area": area_id, "fragment": {"nodes": [], "edges": []}}
    people, weights = rows[0]["people"], rows[0]["weights"]
    nodes = [{"id": p["id"], "label": "Person", "props": {"name": p["name"]}} for p in people]
    nodes.append({"id": area_id, "label": "Area", "props": {"name": health[0]["area"]}})
    edges = [{"src": a["id"], "dst": b["id"], "type": "TIE", "props": {"weight": w}}
             for a, b, w in zip(people, people[1:], weights)]
    edges.append({"src": to["id"], "dst": area_id, "type": "WORKED_ON", "props": {}})
    return {"to": to, "path": people, "weights": weights, "area": area_id, "fragment": {"nodes": nodes, "edges": edges}}
