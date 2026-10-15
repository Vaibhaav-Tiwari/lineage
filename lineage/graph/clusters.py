"""Topic clusters of proposals: community detection (label propagation) on the
PEP citation graph. Each cluster is named after its most influential member
(highest PageRank). On people, the same algorithm finds one giant community —
Python's core developers are densely connected — so we cluster proposals."""

from lineage.db import ro
from lineage.graph import queries as Q


async def pep_clusters(g, min_size: int = 6, limit: int = 12) -> list[dict]:
    out = []
    for row in (await ro(g, Q.PEP_COMMUNITIES, {"min": min_size}))[:limit]:
        members = sorted(row["members"], key=lambda m: -(m["pagerank"] or 0))
        areas = await ro(g, Q.AREA_COUNTS_FOR_PEPS, {"ids": [m["id"] for m in members]})
        out.append({"id": row["cid"], "size": row["size"], "label": members[0]["title"],
                    "anchor": members[0]["id"], "top": [{"id": m["id"], "number": m["number"], "title": m["title"]} for m in members[:8]],
                    "areas": [a["area"] for a in areas]})
    return out
