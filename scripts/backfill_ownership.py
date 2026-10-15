"""One-off: add per-commit dates to COMMITTED_TO edges and costs to TIE edges in an existing graph,
from the cached GitHub responses, without re-running the whole ingest.

    uv run python -m scripts.backfill_ownership [--graph lineage:company]
"""

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from lineage.db import get_db, rw
from lineage.graph import queries as Q
from lineage.ingest.github import aggregate_commits

SET_DATES = """
UNWIND $rows AS r
MATCH (p:Person)-[c:COMMITTED_TO]->(:Area {id: r.area_id})
WHERE toLower(p.github) = r.github
SET c.dates = r.dates
RETURN count(c) AS n
"""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="lineage:company")
    a = ap.parse_args()
    db = await get_db()
    g = db.select_graph(a.graph)
    areas = yaml.safe_load(Path("config/areas.yaml").read_text())
    total = 0
    for area, paths in areas.items():
        commits = []
        for path in paths:
            for page in range(1, 6):
                f = Path("data/raw/github") / f"commits-{area}-{path.replace('/', '_')}-{page}.json"
                if not f.exists():
                    break
                batch = json.loads(f.read_text())
                commits += batch
                if len(batch) < 100:
                    break
        rows = [{"area_id": f"area:{area}", "github": r["github"], "dates": r["dates"]} for r in aggregate_commits(commits, area)]
        if rows:
            total += (await rw(g, SET_DATES, {"rows": rows}))[0]["n"]
    await rw(g, Q.MATERIALIZE_TIES)
    print(f"dates on {total} COMMITTED_TO edges; TIE costs set")
    await db.aclose()


if __name__ == "__main__":
    asyncio.run(main())
