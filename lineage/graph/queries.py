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

# --- Ingest: people (after identity resolution) ---------------------------

# Write each resolved person's name and handles; aliases is a list of strings.
UPSERT_PEOPLE = """
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = coalesce(r.name, p.name), p.github = r.github, p.discourse = r.discourse, p.aliases = r.aliases
"""

# --- Ingest: PEP text --------------------------------------------------------

# One Chunk per section piece, with its embedding stored as a vecf32 vector.
UPSERT_CHUNKS = """
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (c:Chunk {id: r.id})
SET c.heading = r.heading, c.text = r.text, c.idx = r.idx, c.emb = vecf32(r.emb)
MERGE (c)-[:PART_OF]->(p)
"""

# PEP text mentions another PEP ("PEP 563", :pep:`563`). Only known PEPs are linked.
UPSERT_REFERENCES = """
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[x:REFERENCES]->(b)
SET x.count = r.count
"""

# The PEP-Delegate header: who was given authority to decide the PEP.
UPSERT_DELEGATES = """
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
MERGE (a)-[:DELEGATE_FOR]->(p)
"""

# --- Ingest: Experts Index (declared ownership) ----------------------------

# Person -[:EXPERT_IN {assignable, inactive}]-> Area, from the devguide table.
UPSERT_EXPERTS = """
UNWIND $rows AS r
MERGE (a:Area {id: r.area_id})
SET a.name = r.area, a.kind = r.kind
MERGE (p:Person {id: r.person_id})
ON CREATE SET p.github = r.github
MERGE (p)-[e:EXPERT_IN]->(a)
SET e.assignable = r.assignable, e.inactive = r.inactive
"""

# --- Ingest: discuss.python.org --------------------------------------------

UPSERT_THREAD = """
MERGE (t:Thread {id: $id})
SET t.title = $title, t.created = date($date), t.posts_count = $posts_count, t.source_url = $url
"""

# Posts with author and thread; embeddings let search find the discussion itself.
UPSERT_POSTS = """
UNWIND $rows AS r
MERGE (po:Post {id: r.id})
SET po.post_number = r.post_number, po.text = r.text, po.created = date(r.date),
    po.source_url = r.url, po.emb = vecf32(r.emb)
WITH po, r
MATCH (t:Thread {id: r.thread_id})
MERGE (po)-[:IN]->(t)
WITH po, r
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
MERGE (a)-[:POSTED]->(po)
"""

LINK_PEP_THREAD = """
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id}), (t:Thread {id: r.thread_id})
MERGE (p)-[:DISCUSSED_IN]->(t)
"""

# Decision provenance: the exact post that announced it, and who posted it.
LINK_DECISION_POST = """
MATCH (d:Decision)-[:DECIDES]->(:PEP {id: $pep_id})
WHERE d.kind IN ['accept', 'reject']
MATCH (a:Person)-[:POSTED]->(po:Post {id: $post_id})
MERGE (d)-[:RECORDED_IN]->(po)
MERGE (d)-[:ANNOUNCED_BY]->(a)
SET d.at = coalesce(d.at, po.created)
"""

LINK_DECISION_THREAD = """
MATCH (d:Decision)-[:DECIDES]->(:PEP {id: $pep_id})
WHERE d.kind IN ['accept', 'reject']
MATCH (t:Thread {id: $thread_id})
MERGE (d)-[:RECORDED_IN]->(t)
"""

# --- Ingest: GitHub (revealed ownership, implementing PRs) -----------------

# Person -[:COMMITTED_TO {count, last_at}]-> Area: who actually works on it (last 12 months).
UPSERT_COMMITTED = """
UNWIND $rows AS r
MERGE (a:Area {id: r.area_id})
ON CREATE SET a.name = r.area
MERGE (p:Person {id: r.person_id})
ON CREATE SET p.github = r.github
MERGE (p)-[c:COMMITTED_TO]->(a)
SET c.count = r.count, c.last_at = date(r.last_at)
"""

# Merged PR whose title names a PEP -[:IMPLEMENTS]-> that PEP.
UPSERT_PRS = """
UNWIND $rows AS r
MATCH (pep:PEP {id: r.pep_id})
MERGE (pr:PR {id: r.id})
SET pr.number = r.number, pr.title = r.title, pr.source_url = r.url,
    pr.merged_at = CASE WHEN r.merged_at IS NULL THEN null ELSE date(r.merged_at) END
MERGE (pr)-[:IMPLEMENTS]->(pep)
WITH pr, r
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.github = r.github
MERGE (a)-[:AUTHORED_PR]->(pr)
"""
