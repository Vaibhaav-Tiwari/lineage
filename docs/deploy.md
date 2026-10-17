# Deploying the public demo (Railway)

The hosted demo runs three services in one Railway project. It uses the **graph-only** backend: no LLM, no API
keys, and nothing from anyone's Claude subscription.

| Service | Built from | What it does |
|---|---|---|
| `falkordb` | `deploy/falkordb/Dockerfile` | FalkorDB 6.0.2 (no Browser) with the company graph on a volume; password-protected, reachable only on Railway's private network |
| `api` | `Dockerfile` (repo root) | the FastAPI app, graph-only, with the embedding model fetched at build time; no raw data cache |
| `web` | `web/Dockerfile` | the Next.js UI; `NEXT_PUBLIC_API_URL` is baked in at build time |

## How the graph gets there

Building the graph from `data/raw` embeds about 24,600 passages and posts. Locally that took most of 10 CPU cores
and about 3 GB of memory for hours, which does not fit a 1 GB Railway service. So the graph is built locally and
copied into the hosted database once. The snapshot is never published (no image layer, no release asset): the graph
holds forum post text that the repo only links to.

The copy, done on 17 Oct 2026:

1. Deploy `falkordb` with a volume at `/var/lib/falkordb/data` and `REDIS_ARGS="--requirepass <pw> --shutdown-on-sigterm nosave"`
   (so a restart can never write an empty database over the volume).
2. Open a temporary TCP proxy (`railway tcp-proxy create --port 6379 --service falkordb`).
3. From the local FalkorDB: `MIGRATE <proxy host> <proxy port> lineage:company 0 900000 COPY AUTH <pw>`, sent through
   stdin so the password is never on a command line; then `SAVE` on the remote.
4. Check the counts (27,959 nodes, 67,601 relationships) and delete the proxy.

## Shared demo

Every visitor shares one demo. The API resets it every hour (`AUTO_RESET_MINUTES=60`): agent memory, the shared
board and the PEP 563 change go back to the start; the company graph is untouched. What-if previews copy the
graph, so only one runs at a time. Browser requests are accepted only from the web app's origin (`CORS_ORIGINS`).

## Deploying

```bash
railway login
railway init --name lineage
railway add --service falkordb
railway add --service api
railway add --service web
# variables (set the same random password on both):
#   falkordb: REDIS_ARGS=--requirepass <pw> --shutdown-on-sigterm nosave, FALKORDB_ARGS=MAX_QUEUED_QUERIES 25 TIMEOUT_DEFAULT 5000 TIMEOUT_MAX 30000 RESULTSET_SIZE 10000
#   api:      FALKOR_HOST=falkordb.railway.internal, FALKOR_PASSWORD=<pw>, AUTO_RESET_MINUTES=60, CORS_ORIGINS=https://<web domain>
#   web:      NEXT_PUBLIC_API_URL=https://<api domain>, NEXT_PUBLIC_SHARED_DEMO=1
railway volume add -m /var/lib/falkordb/data   # with the falkordb service linked
railway up deploy/falkordb --path-as-root --service falkordb
railway up --service api
railway up web --path-as-root --service web
```

`.railwayignore` keeps the raw cache, docs and the web app out of the API upload. Live: web
https://web-production-662e.up.railway.app, API https://api-production-9be5d.up.railway.app.
