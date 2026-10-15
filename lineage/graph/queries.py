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

AREAS = "MATCH (a:Area) RETURN a.id AS id, a.name AS name, a.kind AS kind"
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
WHERE NOT a:Event OR coalesce(a.applied, true) = true   // replay events stay hidden until applied
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

# --- Agent memory (one graph per agent) -------------------------------------------
# Evidence nodes are stubs pointing at company-graph ids: Cypher cannot cross
# graphs, so lineage crosses them by id (see graph/ripple.py).

CREATE_ANSWER = """
CREATE (a:Answer {id: $id, question: $question, text: $text, created_at: $now, as_of: $as_of, stale: false})
"""

LINK_EVIDENCE = """
MATCH (x {id: $src})
UNWIND $refs AS ref
MERGE (e:Evidence {ref: ref})
ON CREATE SET e.id = 'ev:' + ref, e.ref_label = split(ref, ':')[0]
MERGE (x)-[:DERIVED_FROM]->(e)
"""

CREATE_BELIEFS = """
MATCH (a:Answer {id: $answer_id})
UNWIND $beliefs AS b
CREATE (bl:Belief {id: b.id, text: b.text, status: b.status, confidence: b.confidence, created_at: $now, stale: false})
MERGE (a)-[:DERIVED_FROM]->(bl)
"""

LIST_BELIEFS = """
MATCH (b:Belief)
WHERE $status IS NULL OR b.status = $status
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence,
       b.stale AS stale, b.stale_because AS stale_because, b.created_at AS created_at
ORDER BY b.created_at
"""

CREATE_ACTION = """
CREATE (x:Action {id: $id, kind: $kind, payload_json: $payload, status: 'pending', created_at: $now})
WITH x
UNWIND $derived_from AS ref
MATCH (y) WHERE (y:Answer OR y:Belief) AND y.id = ref
MERGE (x)-[:DERIVED_FROM]->(y)
"""

# --- User memory (one graph per user) ----------------------------------------------

CREATE_EPISODE = """
CREATE (e:Episode {id: $id, question: $question, answer_id: $answer_id, at: $now})
WITH e
UNWIND $areas AS ref
MERGE (i:Interest {area_ref: ref})
ON CREATE SET i.weight = 0
SET i.weight = i.weight + 1, i.last_at = $now
MERGE (e)-[:SUGGESTS]->(i)
"""

EXPLAIN_INTEREST = """
MATCH (e:Episode)-[r:SUGGESTS]->(i:Interest {area_ref: $area})
RETURN e.id AS eid, e.question AS q, e.at AS at, i.area_ref AS area, i.weight AS w
ORDER BY e.at
"""

FORGET_DECREMENT = "MATCH (:Episode {id: $id})-[:SUGGESTS]->(i:Interest) SET i.weight = i.weight - 1"
FORGET_EPISODE = "MATCH (e:Episode {id: $id}) DELETE e"
DROP_EMPTY_INTERESTS = "MATCH (i:Interest) WHERE i.weight <= 0 DELETE i"
LIST_INTERESTS = "MATCH (i:Interest) RETURN i.area_ref AS area, i.weight AS weight, i.last_at AS last_at ORDER BY weight DESC"

# Areas touched by a set of cited PEPs (for per-user interest memory).
AREAS_OF_PEPS = """
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN DISTINCT a.id AS id
"""

# --- Steward: staleness ripple -----------------------------------------------------

SUPERSEDERS = """
MATCH (s:PEP)-[:SUPERSEDES]->(c:PEP)
WHERE c.id IN $changed
RETURN DISTINCT s.id AS id
"""

# PEPs that cite or require a changed PEP, up to N hops (bounded: safe on cycles).
_RIPPLE_SOFT = """
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..{n}]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
"""
RIPPLE_SOFT_1 = _RIPPLE_SOFT.replace("{n}", "1")
RIPPLE_SOFT_2 = _RIPPLE_SOFT.replace("{n}", "2")
RIPPLE_SOFT_3 = _RIPPLE_SOFT.replace("{n}", "3")

MARK_PEPS_STALE = "MATCH (p:PEP) WHERE p.id IN $ids SET p.stale = true, p.stale_because = $reason"

MARK_CHUNKS_STALE = """
MATCH (ch:Chunk)-[:PART_OF]->(p:PEP)
WHERE p.id IN $ids
SET ch.stale = true, ch.stale_because = $reason
RETURN ch.id AS id
"""

RIPPLE_EDGES = """
MATCH (a:PEP)-[r:REFERENCES|REQUIRES|SUPERSEDES]->(b:PEP)
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS s, 'PEP' AS sl, {number: a.number, title: a.title, stale: a.stale} AS sp, type(r) AS t, {} AS rp,
       b.id AS d, 'PEP' AS dl, {number: b.number, title: b.title, stale: b.stale} AS dp
"""

CLEAR_STALE = "MATCH (n) WHERE n.stale = true SET n.stale = false, n.stale_because = null"

# --- Steward: fan-out into an agent's memory graph ----------------------------------

# Everything an agent built on the changed evidence (walks DERIVED_FROM upward).
DEPENDENTS_OF_EVIDENCE = """
MATCH (e:Evidence) WHERE e.ref IN $refs
SET e.stale = true, e.stale_because = $reason
WITH e
MATCH (x)-[:DERIVED_FROM*1..5]->(e)
WHERE x:Belief OR x:Answer OR x:Action
RETURN DISTINCT x.id AS id, labels(x)[0] AS label, x.status AS status
"""

MARK_BELIEFS_STALE = """
MATCH (b:Belief) WHERE b.id IN $ids AND b.status <> 'stale'
SET b.prev_status = b.status, b.status = 'stale', b.stale = true, b.stale_because = $reason
"""
MARK_ANSWERS_STALE = "MATCH (a:Answer) WHERE a.id IN $ids SET a.stale = true, a.stale_because = $reason"
BLOCK_ACTIONS = """
MATCH (x:Action) WHERE x.id IN $ids AND x.status = 'pending'
SET x.status = 'blocked', x.blocked_by_steward = true, x.reason = $reason
RETURN x.id AS id
"""

# Undo of a change event inside an agent graph: put beliefs/actions back as they were.
RESTORE_BELIEFS = """
MATCH (b:Belief) WHERE b.prev_status IS NOT NULL
SET b.status = b.prev_status, b.prev_status = null, b.stale = false, b.stale_because = null
"""
RESTORE_ACTIONS = """
MATCH (x:Action) WHERE x.blocked_by_steward = true AND x.status = 'blocked'
SET x.status = 'pending', x.reason = null, x.blocked_by_steward = null
"""

# --- Action gate --------------------------------------------------------------------

# An action may run only if nothing it was derived from is stale or tentative.
GATE_OFFENDING_PATH = """
MATCH p = (a:Action {id: $id})-[:DERIVED_FROM*1..5]->(x)
WHERE x.stale = true OR (x:Belief AND x.status = 'tentative')
RETURN [n IN nodes(p) | n.id] AS path, x.stale AS stale, x.status AS status,
       coalesce(x.stale_because, '') AS why, coalesce(x.ref, x.id) AS culprit
LIMIT 1
"""

ACTION_NODE = "MATCH (x:Action {id: $id}) RETURN x.status AS status, x.kind AS kind, x.payload_json AS payload"

EXECUTE_ACTION = """
MATCH (x:Action {id: $id})
SET x.status = 'done', x.done_at = $now
CREATE (o:Outbox {id: $oid, action_id: $id, kind: x.kind, payload_json: x.payload_json, at: $now})
RETURN o.id AS id
"""

SET_ACTION_BLOCKED = "MATCH (x:Action {id: $id}) SET x.status = 'blocked', x.reason = $reason"

# Root cause first: the longest chain down to a stale Evidence stub.
GATE_ROOT_CAUSE_PATH = """
MATCH p = (a:Action {id: $id})-[:DERIVED_FROM*1..5]->(e:Evidence)
WHERE e.stale = true
RETURN [n IN nodes(p) | n.id] AS path, true AS stale, null AS status,
       coalesce(e.stale_because, '') AS why, e.ref AS culprit
ORDER BY length(p) DESC
LIMIT 1
"""

# --- Shared coordination board (lineage:shared) ------------------------------------

UPSERT_FIX_TASKS = """
UNWIND $rows AS r
MERGE (t:FixTask {id: r.id})
ON CREATE SET t.status = 'open', t.created_at = $now, t.kind = r.kind, t.target_ref = r.target_ref,
              t.reason = r.reason, t.suggested = r.suggested, t.event = r.event
RETURN t.id AS id
"""

# Atomic claim. One query = one atomic unit, and FalkorDB serialises writes per
# graph, so two agents can never claim the same task (no locks needed).
CLAIM_NEXT = """
MATCH (t:FixTask)
WHERE t.status = 'open' OR (t.status = 'claimed' AND t.claim_until <= $now)
WITH t ORDER BY t.created_at, t.id LIMIT 1
SET t.status = 'claimed', t.claimed_by = $agent, t.claim_until = $until
MERGE (a:Agent {name: $agent})
MERGE (a)-[c:CLAIMED]->(t)
SET c.until = $until
RETURN t.id AS id, t.kind AS kind, t.target_ref AS target_ref, t.reason AS reason, t.suggested AS suggested
"""

COMPLETE_TASK = """
MATCH (t:FixTask {id: $id})
WHERE t.claimed_by = $agent AND t.status = 'claimed'
SET t.status = 'done', t.done_at = $now
RETURN t.id AS id
"""

LIST_TASKS = """
MATCH (t:FixTask)
WHERE $status IS NULL OR t.status = $status
RETURN t.id AS id, t.kind AS kind, t.target_ref AS target_ref, t.reason AS reason, t.status AS status,
       t.claimed_by AS claimed_by, t.suggested AS suggested, t.created_at AS created_at
ORDER BY t.created_at, t.id
"""

# Who should review a PEP: active listed experts of the areas it concerns.
AREA_OWNERS_OF_PEPS = """
MATCH (p:PEP)-[:CONCERNS]->(:Area)<-[e:EXPERT_IN]-(x:Person)
WHERE p.id IN $ids AND (e.inactive IS NULL OR e.inactive = false)
RETURN p.id AS pep, p.title AS title, collect(DISTINCT coalesce(x.github, x.name)) AS owners
"""

# --- Ownership drift: declared (Experts Index) vs revealed (commits) -------------

TRACKED_AREAS = "MATCH (:Person)-[:COMMITTED_TO]->(a:Area) RETURN DISTINCT a.id AS id"

DRIFT_DECLARED = """
MATCH (p:Person)-[e:EXPERT_IN]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, coalesce(e.inactive, false) AS inactive
"""

DRIFT_REVEALED = """
MATCH (p:Person)-[c:COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, c.count AS commits, c.last_at AS last_at
"""

AREA_NAMES = "MATCH (a:Area) WHERE a.id IN $areas RETURN a.id AS id, a.name AS name"

# --- What-if (runs on a GRAPH.COPY fork) -------------------------------------------

PERSON_EXISTS = "MATCH (p:Person {id: $id}) RETURN p.id AS id, coalesce(p.name, p.github) AS name"

# Collaboration clusters (size >= 2) via weakly connected components.
COLLAB_COMPONENTS = """
CALL algo.WCC({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATED']}) YIELD node, componentId
WITH componentId, count(node) AS size
WHERE size >= 2
RETURN count(componentId) AS n
"""

# Areas where someone is "active": listed and not inactive, or >= 3 commits.
ACTIVE_IN_AREAS = """
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas AND ((type(r) = 'EXPERT_IN' AND coalesce(r.inactive, false) = false)
                          OR (type(r) = 'COMMITTED_TO' AND r.count >= 3))
RETURN a.id AS id, a.name AS name, count(DISTINCT p) AS n
"""

AREAS_OF_PERSON = """
MATCH (:Person {id: $id})-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
RETURN DISTINCT a.id AS id
"""

DELETE_PERSON = "MATCH (p:Person {id: $id}) DELETE p"

TOP_COLLABORATORS = """
MATCH (:Person {id: $id})-[c:COLLABORATED]-(y:Person)
RETURN coalesce(y.name, y.github, y.id) AS who, c.weight AS w
ORDER BY w DESC LIMIT 5
"""

AREA_COMMITTERS = """
MATCH (y:Person)-[c:COMMITTED_TO]->(a:Area {id: $area})
WHERE y.id <> $id
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, c.count AS n
ORDER BY n DESC LIMIT 3
"""

PERSON_FOOTPRINT = """
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH p, count(DISTINCT pep) AS authored
OPTIONAL MATCH (d:Decision)-[:ANNOUNCED_BY]->(p)
RETURN authored, count(DISTINCT d) AS announced
"""

# --- API listings --------------------------------------------------------------------

LIST_EVENTS = """
MATCH (e:Event)-[:AFFECTS]->(p:PEP)
RETURN e.id AS id, e.kind AS kind, e.summary AS summary, toString(e.at) AS at, e.applied AS applied,
       e.source_url AS source_url, p.id AS pep, e.payload_json AS payload
ORDER BY at
"""

LIST_ACTIONS = """
MATCH (x:Action)
RETURN x.id AS id, x.kind AS kind, x.status AS status, x.reason AS reason, x.payload_json AS payload, x.created_at AS created_at
ORDER BY x.created_at
"""

SEARCH_PEOPLE = """
MATCH (p:Person)
WHERE toLower(coalesce(p.name, '')) CONTAINS toLower($q) OR toLower(coalesce(p.github, '')) CONTAINS toLower($q)
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
RETURN p.id AS id, p.name AS name, p.github AS github, count(pep) AS peps
ORDER BY peps DESC, id LIMIT 15
"""

# --- Index card for one node --------------------------------------------------------

_CARD = """
MATCH (n:{label} {id: $id})
OPTIONAL MATCH (n)-[r]-(m)
WITH n, r, m LIMIT 60
RETURN properties(n) AS props, type(r) AS rel, startNode(r).id = n.id AS outgoing, m.id AS mid, labels(m)[0] AS ml,
       coalesce(m.title, m.name, m.github, m.kind, m.heading) AS mname
"""
CARD_BY_LABEL = {lab: _CARD.replace("{label}", lab) for lab in
                 ("PEP", "Person", "Decision", "Thread", "Post", "PR", "Chunk", "Area", "Event", "Team")}

BELIEFS_ON_REF = """
MATCH (b:Belief)-[:DERIVED_FROM]->(:Evidence {ref: $ref})
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence
"""

DELETE_CONCERNS = "MATCH (:PEP)-[r:CONCERNS]->(:Area) DELETE r"

# Graph-only backend: which known module names appear in a question.
AREAS_NAMED_IN = """
MATCH (a:Area)
WHERE size(a.name) >= 4 AND toLower($q) CONTAINS toLower(a.name)
RETURN a.name AS name
ORDER BY size(a.name) DESC
LIMIT 1
"""

# --- Algorithms as agent tools ---------------------------------------------------------

RESOLVE_PERSON = """
MATCH (p:Person)
WHERE toLower(p.name) = toLower($q) OR toLower(p.github) = toLower($q)
   OR toLower(p.name) CONTAINS toLower($q)
RETURN p.id AS id, (toLower(coalesce(p.name, '')) = toLower($q) OR toLower(coalesce(p.github, '')) = toLower($q)) AS exact
ORDER BY exact DESC LIMIT 1
"""

RESOLVE_AREA = "MATCH (a:Area) WHERE toLower(a.name) = toLower($q) RETURN a.id AS id LIMIT 1"

# Shortest chain between two things (FalkorDB allows shortestPath only in WITH/RETURN).
_SHORTEST = """
MATCH (a:{la} {id: $a}), (b:{lb} {id: $b})
WITH a, b, shortestPath((a)-[:AUTHORED|DECIDES|ANNOUNCED_BY|SUPERSEDES|REFERENCES|REQUIRES|IMPLEMENTS|AUTHORED_PR|COLLABORATED|DELEGATE_FOR|EXPERT_IN|COMMITTED_TO|CONCERNS*1..6]-(b)) AS p
WHERE p IS NOT NULL
RETURN [n IN nodes(p) | {id: n.id, label: labels(n)[0], name: coalesce(n.name, n.github, n.title, n.kind)}] AS nodes,
       [r IN relationships(p) | {type: type(r), src: startNode(r).id, dst: endNode(r).id}] AS rels
"""

# Who bridges otherwise separate groups of collaborators. Runs on TIE (two-way copies of
# COLLABORATED): FalkorDB's betweenness follows edge direction, and collaboration has none.
BETWEENNESS_PEOPLE = """
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['TIE']}) YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC
"""

# Topic clusters in the proposal citation graph (community detection via label propagation).
PEP_COMMUNITIES = """
CALL algo.labelPropagation({nodeLabels: ['PEP'], relationshipTypes: ['REFERENCES', 'REQUIRES', 'SUPERSEDES']}) YIELD node, communityId
WITH communityId, collect(node) AS ps
WHERE size(ps) >= $min
RETURN communityId AS cid, size(ps) AS size,
       [p IN ps | {id: p.id, number: p.number, title: p.title, pagerank: coalesce(p.pagerank, 0.0)}] AS members
ORDER BY size DESC
"""

AREA_COUNTS_FOR_PEPS = """
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN a.name AS area, count(p) AS n
ORDER BY n DESC LIMIT 4
"""

# Two-way TIE edges for direction-sensitive algorithms (betweenness).
MATERIALIZE_TIES = """
MATCH (a:Person)-[c:COLLABORATED]->(b:Person)
MERGE (a)-[t1:TIE]->(b) SET t1.weight = c.weight
MERGE (b)-[t2:TIE]->(a) SET t2.weight = c.weight
"""

# Undo of a change event on the shared board: drop the review tasks it opened.
DELETE_TASKS_OF_EVENT = "MATCH (t:FixTask) WHERE t.event = $event DELETE t"

# --- What-if, generalised: groups of people; previews of reversing a proposal ---------

PERSONS_EXIST = "MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, coalesce(p.name, p.github, p.id) AS name"
AREAS_OF_PEOPLE = "MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area) WHERE p.id IN $ids RETURN DISTINCT a.id AS id"
DELETE_PEOPLE = "MATCH (p:Person) WHERE p.id IN $ids DELETE p"

TOP_COLLABORATORS_OF_GROUP = """
MATCH (x:Person)-[c:COLLABORATED]-(y:Person)
WHERE x.id IN $ids AND NOT y.id IN $ids
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, sum(c.weight) AS w
ORDER BY w DESC LIMIT 5
"""

AREA_COMMITTERS_EXCEPT = """
MATCH (y:Person)-[c:COMMITTED_TO]->(a:Area {id: $area})
WHERE NOT y.id IN $ids
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, c.count AS n
ORDER BY n DESC LIMIT 3
"""

GROUP_FOOTPRINT = """
MATCH (p:Person) WHERE p.id IN $ids
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH collect(DISTINCT pep) AS peps
OPTIONAL MATCH (d:Decision)-[:ANNOUNCED_BY]->(q:Person) WHERE q.id IN $ids
RETURN size(peps) AS authored, count(DISTINCT d) AS announced
"""

# People search: names/handles that START with the text first, then word starts, then anywhere.
SEARCH_PEOPLE_RANKED = """
MATCH (p:Person)
WITH p, toLower(coalesce(p.name, '')) AS n, toLower(coalesce(p.github, '')) AS h, toLower($q) AS q
WHERE n CONTAINS q OR h CONTAINS q
WITH p, CASE WHEN n STARTS WITH q OR h STARTS WITH q THEN 0 WHEN n CONTAINS (' ' + q) THEN 1 ELSE 2 END AS rank
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH p, rank, count(pep) AS peps
OPTIONAL MATCH (p)-[c:COMMITTED_TO]->(:Area)
RETURN p.id AS id, coalesce(p.name, p.github) AS name, p.github AS handle, peps, coalesce(sum(c.count), 0) AS commits, rank
ORDER BY rank, peps DESC, commits DESC, name
LIMIT 8
"""

SEARCH_PEPS = """
MATCH (p:PEP)
WHERE toString(p.number) STARTS WITH $q OR toLower(p.title) CONTAINS toLower($q)
RETURN p.id AS id, p.number AS number, p.title AS title, p.status AS status
ORDER BY CASE WHEN toString(p.number) = $q THEN 0 ELSE 1 END, coalesce(p.pagerank, 0) DESC
LIMIT 8
"""

PEP_BRIEFS = """
MATCH (p:PEP) WHERE p.id IN $ids
RETURN p.id AS id, p.number AS number, p.title AS title, p.status AS status, toString(p.created) AS created
ORDER BY coalesce(p.pagerank, 0) DESC
"""

# How each dependent rests on the reversed proposal (what-if preview).
DEPENDENT_RELATIONS = """
MATCH (d:PEP)-[r:REFERENCES|REQUIRES]->(:PEP {id: $pid})
WHERE d.id IN $ids
RETURN d.id AS id, type(r) AS rel
"""

# The agent's current answers that rest on any of these refs (read-only, for the preview graph).
DEPENDENT_ANSWERS = """
MATCH (e:Evidence) WHERE e.ref IN $refs
MATCH (a:Answer)-[:DERIVED_FROM*1..5]->(e)
WHERE coalesce(a.stale, false) = false
RETURN DISTINCT a.id AS id, a.text AS text, e.ref AS ref
"""

# Who left, and how they were tied to the modules their leaving affects (departure what-if graph).
PEOPLE_AREA_LINKS = """
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
WHERE p.id IN $ids AND a.id IN $areas
RETURN DISTINCT p.id AS p, type(r) AS t, a.id AS a
"""

CHUNKS_OF_PEPS = "MATCH (c:Chunk)-[:PART_OF]->(p:PEP) WHERE p.id IN $ids RETURN c.id AS id"

# Read-only twin of DEPENDENTS_OF_EVIDENCE: what an agent built on these ids (nothing is marked).
DEPENDENTS_PREVIEW = """
MATCH (e:Evidence) WHERE e.ref IN $refs
MATCH (x)-[:DERIVED_FROM*1..5]->(e)
WHERE (x:Belief AND x.status <> 'stale') OR (x:Answer AND coalesce(x.stale, false) = false) OR (x:Action AND x.status = 'pending')
RETURN labels(x)[0] AS label, count(DISTINCT x) AS n
"""

# --- Explaining a missing answer (lineage/graph/miss.py) ---------------------------------
PEP_BRIEF = "MATCH (p:PEP {number: $n}) RETURN p.number AS number, p.title AS title, p.status AS status, toString(p.created) AS created"

NEAREST_PEPS = """
MATCH (p:PEP)
RETURN p.number AS number, p.title AS title
ORDER BY abs(p.number - $n), p.number
LIMIT 2
"""

FIRST_PEP_ABOUT = """
MATCH (p:PEP)
WHERE toLower(p.title) CONTAINS toLower($name)
RETURN p.number AS number, toString(p.created) AS created
ORDER BY p.created LIMIT 1
"""

FIRST_PEP_CONCERNING = """
MATCH (p:PEP)-[:CONCERNS]->(:Area {name: $name})
RETURN p.number AS number, toString(p.created) AS created
ORDER BY p.created LIMIT 1
"""

EXAMPLE_PEP_AT = """
MATCH (p:PEP)
WHERE $as_of IS NULL OR p.created <= date($as_of)
RETURN p.number AS number
ORDER BY coalesce(p.pagerank, 0) DESC LIMIT 1
"""
