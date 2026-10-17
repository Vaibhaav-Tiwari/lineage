"""Start the API for a hosted deployment: build the company graph on first boot, then serve.

    python -m lineage.deploy            (reads FALKOR_HOST / FALKOR_PASSWORD / PORT from the environment)

The graph is rebuilt from the raw cache committed in data/raw, with no network, so a fresh database volume
gets exactly the data the repo describes. The hosted images ship the graph inside the database instead, with no
raw cache, so there a missing graph is reported, not rebuilt.
"""

import asyncio
import os

from lineage.db import get_db, ro


async def seed_if_empty(db, name: str = "lineage:company", pipeline=None, data_dir: str = "data/raw",
                        config_dir: str = "config") -> str:
    if name in await db.list_graphs() and (await ro(db.select_graph(name), "MATCH (n) RETURN count(n) AS n"))[0]["n"]:
        return "present"
    if not os.path.isdir(data_dir):  # the hosted image ships the graph in the database, not the raw cache
        return "missing"
    if pipeline is None:
        from lineage.ingest.run import run_pipeline as pipeline
    await pipeline(db.select_graph(name), data_dir, config_dir, offline=True, rewind=True, quiet=False)
    return "seeded"


async def _seed() -> None:
    for attempt in range(30):  # the database may still be starting
        try:
            db = await get_db()
            await db.list_graphs()
            break
        except Exception as e:  # noqa: BLE001
            print(f"waiting for FalkorDB ({e})", flush=True)
            await asyncio.sleep(2)
    else:
        raise SystemExit("FalkorDB never became reachable")
    print(f"company graph: {await seed_if_empty(db)}", flush=True)
    await db.aclose()


def main() -> None:
    asyncio.run(_seed())
    port = os.environ.get("PORT", "8000")
    os.execvp("uvicorn", ["uvicorn", "lineage.api.main:app", "--host", "0.0.0.0", "--port", port])


if __name__ == "__main__":
    main()
