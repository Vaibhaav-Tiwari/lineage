"""Every Cypher query the product depends on, as named constants.

Writes use `UNWIND $rows AS r` + MERGE on stable ids so ingestion is batched
(FalkorDB serialises writes per graph) and idempotent (safe to re-run).
docs/queries.md is generated from this file.
"""

# --- Ingest: PEP metadata (peps.json) ------------------------------------

# Upsert one PEP node per proposal; dates arrive as ISO strings.
UPSERT_PEPS = """
UNWIND $rows AS r
MERGE (p:PEP {id: r.id})
SET p.number = r.number, p.title = r.title, p.status = r.status, p.type = r.type,
    p.topic = r.topic, p.python_version = r.python_version, p.source_url = r.url,
    p.created = CASE WHEN r.created IS NULL THEN null ELSE date(r.created) END
"""

# Link authors to the PEPs they wrote (Person nodes are created if missing).
UPSERT_AUTHORS = """
UNWIND $rows AS r
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
WITH a, r
MATCH (p:PEP {id: r.pep_id})
MERGE (a)-[:AUTHORED]->(p)
"""

# New PEP -[:SUPERSEDES]-> old PEP (from superseded_by / replaces).
UPSERT_SUPERSEDES = """
UNWIND $rows AS r
MATCH (n:PEP {id: r.src}), (o:PEP {id: r.dst})
MERGE (n)-[:SUPERSEDES]->(o)
"""

# PEP -[:REQUIRES]-> PEP it depends on.
UPSERT_REQUIRES = """
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[:REQUIRES]->(b)
"""

# One Decision node per outcome (accept / reject / supersede / withdraw / defer).
UPSERT_DECISIONS = """
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (d:Decision {id: r.id})
SET d.kind = r.kind, d.source_url = r.source_url,
    d.at = CASE WHEN r.at IS NULL THEN null ELSE date(r.at) END
MERGE (d)-[:DECIDES]->(p)
"""
