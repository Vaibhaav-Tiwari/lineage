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


def slim_commits(commits: list[dict]) -> list[dict]:
    """Keep only what the product uses (sha, author login, date): no names, emails or messages in the repo."""
    return [{"sha": c.get("sha"), "author": {"login": (c.get("author") or {}).get("login")} if c.get("author") else None,
             "commit": {"author": {"date": c["commit"]["author"]["date"]}}} for c in commits]


async def load_worked_on(g, rows: list[dict], resolver) -> None:
    """Full commit history per person and module (WORKED_ON), so ownership can be asked as of any date."""
    out = [{"area_id": ids.area(r["area"]), "area": r["area"], "github": r["github"], "dates": r["dates"],
            "person_id": resolver.resolve(github=r["github"])} for r in rows]
    await write_batch(g, Q.UPSERT_WORKED_ON, out)


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


HISTORY_SINCE = "2015-01-01T00:00:00Z"


async def fetch_history(areas: dict, extra: dict, data_dir: Path, headers: dict, offline: bool,
                        since: str = HISTORY_SINCE, max_pages: int = 60) -> dict[str, list]:
    """Every commit since `since` that touched each module's paths (cached per page), for ownership over time."""
    from lineage.ingest.cache import fetch_cached

    out: dict[str, list] = {}
    for area, paths in areas.items():
        commits, seen = [], set()
        for path in list(paths) + list(extra.get(area, [])):
            for page in range(1, max_pages + 1):
                key = f"hist-{area}-{path.replace('/', '_')}-{page}.json"
                url = f"{API}/repos/python/cpython/commits?path={path}&since={since}&per_page=100&page={page}"
                path_ = Path(data_dir) / "github" / "history" / key
                raw = await fetch_cached(url, path_, headers=headers, offline=offline)
                batch = json.loads(raw) if raw else []
                if raw and b'"email"' in raw:  # cache only what we use
                    batch = slim_commits(batch)
                    path_.write_text(json.dumps(batch))
                for c in batch:
                    if c.get("sha") not in seen:  # a commit can touch two paths of one module
                        seen.add(c.get("sha"))
                        commits.append({"author": c.get("author"), "commit": {"author": {"date": c["commit"]["author"]["date"]}}})
                if len(batch) < 100:
                    break
        out[area] = commits
    return out
