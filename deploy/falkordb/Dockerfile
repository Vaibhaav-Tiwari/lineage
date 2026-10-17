# FalkorDB for the hosted demo. The company graph lives on the service's volume (/var/lib/falkordb/data),
# loaded once from a snapshot of a graph built by `python -m lineage.ingest.run --offline --rewind-replays`
# (see docs/deploy.md). The snapshot is never published: the graph holds forum text the repo only links to.
FROM falkordb/falkordb:6.0.2
# no FalkorDB Browser in the hosted demo: it is not exposed and would only take memory
ENV BROWSER=0
