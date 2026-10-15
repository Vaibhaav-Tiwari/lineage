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
    return sorted(out, key=lambda r: r["area"])
