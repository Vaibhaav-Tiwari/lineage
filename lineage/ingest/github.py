"""CPython on GitHub → revealed ownership (COMMITTED_TO) and IMPLEMENTS edges."""

import json
import re
from pathlib import Path

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
        a = agg.setdefault(login, {"github": login, "area": area, "count": 0, "last_at": day, "dates": []})
        a["count"] += 1
        a["last_at"] = max(a["last_at"], day)
        a["dates"].append(day)
    for a in agg.values():
        a["dates"].sort()
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


def user_display_name(user: dict) -> str | None:
    """The public profile name, unless it is blank or just the handle again."""
    name = (user.get("name") or "").strip()
    return name if name and name.lower() != (user.get("login") or "").lower() else None


async def fetch_github_names(handles, data_dir: Path, headers: dict, offline: bool) -> dict[str, str]:
    """handle -> public display name, one cached GET /users/{login} per handle."""
    from lineage.ingest.cache import fetch_cached

    out: dict[str, str] = {}
    for h in sorted({h.lower() for h in handles if h}):
        try:
            raw = await fetch_cached(f"{API}/users/{h}", Path(data_dir) / "github" / "users" / f"{h}.json",
                                     min_interval=0.2, headers=headers, offline=offline)
        except Exception:  # renamed / deleted account: keep the handle
            continue
        user = json.loads(raw) if raw else {}
        if set(user) - {"login", "name"}:  # keep only what we use; no emails or bios in the repo
            user = {"login": user.get("login"), "name": user.get("name")}
            (Path(data_dir) / "github" / "users" / f"{h}.json").write_text(json.dumps(user))
        name = user_display_name(user)
        if name:
            out[h] = name
    return out
