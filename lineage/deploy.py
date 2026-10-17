"""Start the API for a hosted deployment: build the company graph on first boot, then serve.

    python -m lineage.deploy            (reads FALKOR_HOST / FALKOR_PASSWORD / PORT from the environment)

The graph is rebuilt from the raw cache committed in data/raw, with no network, so a fresh database volume
gets exactly the data the repo describes. A volume that already holds the graph is left alone.
"""

import asyncio
import os

from lineage.db import get_db, ro


async def seed_if_empty(db, name: str = "lineage:company", pipeline=None, data_dir: str = "data/raw",
                        config_dir: str = "config") -> str:
    if name in await db.list_graphs() and (await ro(db.select_graph(name), "MATCH (n) RETURN count(n) AS n"))[0]["n"]:
        return "present"
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
