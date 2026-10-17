# Deploying the public demo (Railway)

The hosted demo runs three services in one Railway project. It uses the **graph-only** backend: no LLM, no API
keys, and nothing from anyone's Claude subscription.

| Service | Built from | What it does |
|---|---|---|
| `falkordb` | `deploy/falkordb/Dockerfile` | FalkorDB 6.0.2 with the company graph baked in as `dump.rdb`; password-protected, reachable only on Railway's private network |
| `api` | `Dockerfile` (repo root) | the FastAPI app, graph-only, with the embedding model fetched at build time |
| `web` | `web/Dockerfile` | the Next.js UI; `NEXT_PUBLIC_API_URL` is baked in at build time |

## Why the graph is baked into the database image

Building the graph from `data/raw` embeds about 24,600 passages and posts. On a laptop that took most of
10 CPU cores and about 3 GB of memory, which does not fit a 1 GB Railway service. So the graph is built once,
locally and from scratch, and its snapshot ships in the database image. Every boot loads it, so a restart is
also a clean reset, and the database needs no volume.

## Shared demo

Every visitor shares one demo. The API resets it every hour (`AUTO_RESET_MINUTES=60`): agent memory, the shared
board and the PEP 563 change go back to the start; the company graph is untouched. What-if previews copy the
graph, so only one runs at a time. Browser requests are accepted only from the web app's origin (`CORS_ORIGINS`).

## Rebuilding the snapshot

```bash
docker network create lineage-seed
docker run -d --name seed-fdb --network lineage-seed -e REDIS_ARGS="--requirepass seed" falkordb/falkordb:6.0.2
docker build -t lineage-api .
docker run --rm --network lineage-seed -e FALKOR_HOST=seed-fdb -e FALKOR_PASSWORD=seed \
  lineage-api python -c "import asyncio; from lineage.deploy import _seed; asyncio.run(_seed())"
docker exec seed-fdb redis-cli -a seed SAVE
docker cp seed-fdb:/var/lib/falkordb/data/dump.rdb deploy/falkordb/dump.rdb
```

## Deploying

```bash
railway login
railway init --name lineage
railway add --service falkordb
railway add --service api
railway add --service web
# variables (set the same random password on both):
#   falkordb: REDIS_ARGS=--requirepass <pw>, FALKORDB_ARGS=MAX_QUEUED_QUERIES 25 TIMEOUT_DEFAULT 5000 TIMEOUT_MAX 30000 RESULTSET_SIZE 10000
#   api:      FALKOR_HOST=falkordb.railway.internal, FALKOR_PASSWORD=<pw>, AUTO_RESET_MINUTES=60, CORS_ORIGINS=https://<web domain>
#   web:      NEXT_PUBLIC_API_URL=https://<api domain>, NEXT_PUBLIC_SHARED_DEMO=1
railway up deploy/falkordb --path-as-root --no-gitignore --service falkordb
railway up --service api
railway up web --path-as-root --service web
```
