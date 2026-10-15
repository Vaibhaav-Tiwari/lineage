"""One-off: load the cached CPython commit history (scripts/fetch_history.py) into an existing graph as
WORKED_ON edges, adding historical committers as people, without re-running the whole ingest.

    GITHUB_TOKEN=$(gh auth token) uv run python -m scripts.backfill_history [--graph lineage:company]
"""

import argparse
import asyncio
from pathlib import Path

import yaml

from lineage.config import settings
from lineage.db import get_db, ro, write_batch
from lineage.graph import queries as Q
from lineage.ingest import github as GH
from lineage.ingest.identity import IdentityResolver


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="lineage:company")
    a = ap.parse_args()
    data, cfg = Path("data/raw"), Path("config")
    token = settings().github_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"} if token else {}
    hist = await GH.fetch_history(yaml.safe_load((cfg / "areas.yaml").read_text()),
                                  yaml.safe_load((cfg / "areas_history.yaml").read_text()) or {}, data, headers, offline=True)
    rows = [r for area, cs in hist.items() for r in GH.aggregate_commits(cs, area)]
    db = await get_db()
    g = db.select_graph(a.graph)
    known = await ro(g, "MATCH (p:Person) RETURN p.id AS id, p.name AS name, p.github AS github, p.discourse AS discourse")
    have = {p["github"].lower() for p in known if p["github"]}
    names = await GH.fetch_github_names([r["github"] for r in rows if r["github"] not in have], data, headers, offline=not token)
    resolver = IdentityResolver(yaml.safe_load((cfg / "aliases.yaml").read_text()) or {}, github_names=names)
    resolver.seed(known)
    for r in rows:
        resolver.resolve(github=r["github"])
    new = resolver.new_people()
    if new:
        await write_batch(g, Q.UPSERT_PEOPLE, new)
    await GH.load_worked_on(g, rows, resolver)
    print(f"{len(rows)} person-module histories; {len(new)} new people; names found for {len(names)} new handles")
    await db.aclose()


if __name__ == "__main__":
    asyncio.run(main())
