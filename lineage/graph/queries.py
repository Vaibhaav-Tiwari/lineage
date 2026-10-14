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

# --- Derived edges -------------------------------------------------------------

# People who co-wrote a PEP (weight 3 per shared PEP).
CO_AUTHOR_PAIRS = """
MATCH (a:Person)-[:AUTHORED]->(p:PEP)<-[:AUTHORED]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT p) AS n
"""

# Distinct posters per thread (pairs are built in Python to avoid a post×post blow-up).
THREAD_POSTERS = """
MATCH (a:Person)-[:POSTED]->(:Post)-[:IN]->(t:Thread)
RETURN t.id AS t, collect(DISTINCT a.id) AS people
"""

# People committing to the same area (weight 2 per shared area).
CO_AREA_PAIRS = """
MATCH (a:Person)-[:COMMITTED_TO]->(ar:Area)<-[:COMMITTED_TO]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT ar) AS n
"""

# Stored once per pair (lower id → higher id); weight is recomputed, so re-runs are safe.
UPSERT_COLLABORATED = """
UNWIND $rows AS r
MATCH (a:Person {id: r.a}), (b:Person {id: r.b})
MERGE (a)-[c:COLLABORATED]->(b)
SET c.weight = r.w
"""

AREAS = "MATCH (a:Area) RETURN a.id AS id, a.name AS name"
PEP_TITLES = "MATCH (p:PEP) RETURN p.id AS id, p.title AS title"

# Full-text search over PEP text chunks for one area name.
CHUNKS_MENTIONING = """
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node
MATCH (node)-[:PART_OF]->(p:PEP)
RETURN p.id AS pep, node.text AS text
"""

UPSERT_CONCERNS = """
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep}), (a:Area {id: r.area})
MERGE (p)-[:CONCERNS]->(a)
"""

# Influence of each PEP in the citation graph, stored for search re-ranking.
PAGERANK_PEPS = """
CALL algo.pageRank('PEP', 'REFERENCES') YIELD node, score
SET node.pagerank = score
"""

# --- Replayable change events ----------------------------------------------------

UPSERT_EVENT = """
MERGE (e:Event {id: $id})
ON CREATE SET e.applied = true
SET e.kind = $kind, e.at = date($at), e.summary = $summary, e.source_url = $source_url, e.payload_json = $payload
WITH e
MATCH (p:PEP {id: $pep_id})
MERGE (e)-[:AFFECTS]->(p)
"""

EVENT_SET_STATUS = "MATCH (p:PEP {id: $pep_id}) SET p.status = $status"

EVENT_DELETE_SUPERSEDES = """
MATCH (n:PEP)-[r:SUPERSEDES]->(:PEP {id: $pep_id})
WHERE n.id IN $by
DELETE r
"""

EVENT_DELETE_DECISION = "MATCH (d:Decision {id: $decision_id}) DELETE d"

EVENT_ADD_SUPERSEDES = """
UNWIND $by AS newer
MATCH (n:PEP {id: newer}), (p:PEP {id: $pep_id})
MERGE (n)-[:SUPERSEDES]->(p)
"""

EVENT_ADD_DECISION = """
MATCH (p:PEP {id: $pep_id})
MERGE (d:Decision {id: $decision_id})
SET d.kind = 'supersede', d.at = date($at), d.source_url = $source_url, d.summary = $summary
MERGE (d)-[:DECIDES]->(p)
"""

EVENT_SET_APPLIED = "MATCH (e:Event {id: $id}) SET e.applied = $applied"

# --- Retrieval ---------------------------------------------------------------------
# NOTE: db.idx.vector.* yields a DISTANCE in `score` (lower = closer). We convert
# to similarity as 1 - distance; never sort the raw score descending.

VECTOR_CHUNKS = """
CALL db.idx.vector.queryNodes('Chunk', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
"""

VECTOR_POSTS = """
CALL db.idx.vector.queryNodes('Post', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:IN]->(:Thread)<-[:DISCUSSED_IN]-(p:PEP)
WHERE $as_of IS NULL OR (node.created <= date($as_of) AND (p.created IS NULL OR p.created <= date($as_of)))
RETURN node.id AS id, 'Post' AS label, 'Discussion' AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, node.source_url AS url, p.pagerank AS pagerank
"""

FULLTEXT_CHUNKS = """
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS ft,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
LIMIT $k
"""

FULLTEXT_PEP_TITLES = """
CALL db.idx.fulltext.queryNodes('PEP', $q) YIELD node, score
WHERE $as_of IS NULL OR node.created IS NULL OR node.created <= date($as_of)
RETURN node.id AS id, 'PEP' AS label, 'Title' AS heading, node.title AS text, score AS ft,
       node.id AS pep_id, node.title AS title, node.number AS number, node.source_url AS url, node.pagerank AS pagerank
LIMIT $k
"""

# --- Agent tools (each returns rows of src/rel/dst "triples") ----------------------

_TRIPLE = """
RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
"""

PEP_NODE = "MATCH (p:PEP {id: $id}) RETURN properties(p) AS p"

# Who/what points at the PEP: decisions, authors, delegates, implementing PRs, events.
INTO_PEP = """
MATCH (a)-[r:DECIDES|AUTHORED|DELEGATE_FOR|IMPLEMENTS|AFFECTS]->(b:PEP {id: $id})
""" + _TRIPLE + " LIMIT 100"

# Where each decision was recorded and who announced it.
DECISION_PROVENANCE = """
MATCH (:PEP {id: $id})<-[:DECIDES]-(a:Decision)-[r:RECORDED_IN|ANNOUNCED_BY]->(b)
""" + _TRIPLE

# The supersede chain in both directions, up to 3 hops.
SUPERSEDE_CHAIN = """
MATCH path = (:PEP {id: $id})-[:SUPERSEDES*1..3]-(:PEP)
UNWIND relationships(path) AS r
WITH DISTINCT r
WITH startNode(r) AS a, r, endNode(r) AS b
""" + _TRIPLE

PEP_THREADS = """
MATCH (a:PEP {id: $id})-[r:DISCUSSED_IN]->(b:Thread)
""" + _TRIPLE + " LIMIT 10"

# Neighbourhood over citation/supersede/require links (hop count fixed per query).
RELATED_1 = """
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..1]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b
""" + _TRIPLE + " LIMIT 200"
RELATED_2 = RELATED_1.replace("*1..1", "*1..2")
RELATED_3 = RELATED_1.replace("*1..1", "*1..3")

FIND_AREA = """
MATCH (a:Area)
WHERE toLower(a.name) = toLower($t) OR toLower(a.name) CONTAINS toLower($t)
RETURN a.id AS id, a.name AS name, toLower(a.name) = toLower($t) AS exact
ORDER BY exact DESC, size(a.name) ASC
LIMIT 1
"""

# Declared (Experts Index) and revealed (commits) owners of one area.
AREA_EXPERTS = """
MATCH (a:Person)-[r:EXPERT_IN|COMMITTED_TO]->(b:Area {id: $id})
""" + _TRIPLE
