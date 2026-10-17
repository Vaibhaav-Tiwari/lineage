# FalkorDB for the hosted demo, with the company graph baked in.
# dump.rdb is a snapshot of a graph built from scratch by `python -m lineage.ingest.run --offline --rewind-replays`
# (see docs/deploy.md). It is loaded at every boot, so a restart is also a clean reset; no volume needed.
FROM falkordb/falkordb:6.0.2
# no FalkorDB Browser in the hosted demo: it is not exposed and would only take memory
ENV BROWSER=0
COPY dump.rdb /var/lib/falkordb/data/dump.rdb
