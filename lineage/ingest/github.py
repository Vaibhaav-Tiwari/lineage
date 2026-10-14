"""CPython on GitHub → revealed ownership (COMMITTED_TO) and IMPLEMENTS edges."""

import re

from lineage import ids
from lineage.db import write_batch
from lineage.graph import queries as Q

API = "https://api.github.com"
_PEP = re.compile(r"\bPEP[\s-]*(\d{1,4})\b", re.I)


def extract_pep_refs(title: str) -> list[int]:
    return sorted({int(m) for m in _PEP.findall(title or "")})


def aggregate_commits(commits: list[dict], area: str) -> list[dict]:
    agg: dict[str, dict] = {}
    for c in commits:
        login = (c.get("author") or {}).get("login")
        if not login:  # deleted / unlinked account
            continue
        login = login.lower()
        day = c["commit"]["author"]["date"][:10]
        a = agg.setdefault(login, {"github": login, "area": area, "count": 0, "last_at": day})
        a["count"] += 1
        a["last_at"] = max(a["last_at"], day)
    return list(agg.values())


async def load_revealed(g, rows: list[dict], resolver) -> None:
    out = [{**r, "area_id": ids.area(r["area"]), "person_id": resolver.resolve(github=r["github"])} for r in rows]
    await write_batch(g, Q.UPSERT_COMMITTED, out)


async def load_prs(g, items: list[dict], resolver) -> None:
    rows = []
    for it in items:
        login = (it.get("user") or {}).get("login") or "ghost"
        merged = ((it.get("pull_request") or {}).get("merged_at") or "")[:10] or None
        for n in extract_pep_refs(it.get("title", "")):
            rows.append({
                "id": ids.pr(it["number"]), "number": it["number"], "title": it["title"], "url": it.get("html_url"),
                "merged_at": merged, "pep_id": ids.pep(n), "github": login.lower(),
                "person_id": resolver.resolve(github=login),
            })
    await write_batch(g, Q.UPSERT_PRS, rows)
