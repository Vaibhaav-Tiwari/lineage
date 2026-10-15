# Cypher queries

Every query Lineage depends on, generated from `lineage/graph/queries.py`. Writes use `UNWIND $rows` + `MERGE` on stable ids, so ingestion is batched and safe to re-run. 

## Ingest: PEP metadata (peps.json)

### `UPSERT_PEPS`

Upsert one PEP node per proposal; dates arrive as ISO strings.

```cypher
UNWIND $rows AS r
MERGE (p:PEP {id: r.id})
SET p.number = r.number, p.title = r.title, p.status = r.status, p.type = r.type,
    p.topic = r.topic, p.python_version = r.python_version, p.source_url = r.url,
    p.created = CASE WHEN r.created IS NULL THEN null ELSE date(r.created) END
```

### `UPSERT_AUTHORS`

Link authors to the PEPs they wrote (Person nodes are created if missing).

```cypher
UNWIND $rows AS r
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
WITH a, r
MATCH (p:PEP {id: r.pep_id})
MERGE (a)-[:AUTHORED]->(p)
```

### `UPSERT_SUPERSEDES`

New PEP -[:SUPERSEDES]-> old PEP (from superseded_by / replaces).

```cypher
UNWIND $rows AS r
MATCH (n:PEP {id: r.src}), (o:PEP {id: r.dst})
MERGE (n)-[:SUPERSEDES]->(o)
```

### `UPSERT_REQUIRES`

PEP -[:REQUIRES]-> PEP it depends on.

```cypher
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[:REQUIRES]->(b)
```

### `UPSERT_DECISIONS`

One Decision node per outcome (accept / reject / supersede / withdraw / defer).

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (d:Decision {id: r.id})
SET d.kind = r.kind, d.source_url = r.source_url,
    d.at = CASE WHEN r.at IS NULL THEN null ELSE date(r.at) END
MERGE (d)-[:DECIDES]->(p)
```

## Ingest: people (after identity resolution)

### `UPSERT_PEOPLE`

Write each resolved person's name and handles; aliases is a list of strings.

```cypher
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = coalesce(r.name, p.name), p.github = r.github, p.discourse = r.discourse, p.aliases = r.aliases
```

## Ingest: PEP text

### `UPSERT_CHUNKS`

One Chunk per section piece, with its embedding stored as a vecf32 vector.

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (c:Chunk {id: r.id})
SET c.heading = r.heading, c.text = r.text, c.idx = r.idx, c.emb = vecf32(r.emb)
MERGE (c)-[:PART_OF]->(p)
```

### `UPSERT_REFERENCES`

PEP text mentions another PEP ("PEP 563", :pep:`563`). Only known PEPs are linked.

```cypher
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[x:REFERENCES]->(b)
SET x.count = r.count
```

### `UPSERT_DELEGATES`

The PEP-Delegate header: who was given authority to decide the PEP.

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
MERGE (a)-[:DELEGATE_FOR]->(p)
```

## Ingest: Experts Index (declared ownership)

### `UPSERT_EXPERTS`

Person -[:EXPERT_IN {assignable, inactive}]-> Area, from the devguide table.

```cypher
UNWIND $rows AS r
MERGE (a:Area {id: r.area_id})
SET a.name = r.area, a.kind = r.kind
MERGE (p:Person {id: r.person_id})
ON CREATE SET p.github = r.github
MERGE (p)-[e:EXPERT_IN]->(a)
SET e.assignable = r.assignable, e.inactive = r.inactive
```

## Ingest: discuss.python.org

### `UPSERT_THREAD`

```cypher
MERGE (t:Thread {id: $id})
SET t.title = $title, t.created = date($date), t.posts_count = $posts_count, t.source_url = $url
```

### `UPSERT_POSTS`

Posts with author and thread; embeddings let search find the discussion itself.

```cypher
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
```

### `LINK_PEP_THREAD`

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id}), (t:Thread {id: r.thread_id})
MERGE (p)-[:DISCUSSED_IN]->(t)
```

### `LINK_DECISION_POST`

Decision provenance: the exact post that announced it, and who posted it.

```cypher
MATCH (d:Decision)-[:DECIDES]->(:PEP {id: $pep_id})
WHERE d.kind IN ['accept', 'reject']
MATCH (a:Person)-[:POSTED]->(po:Post {id: $post_id})
MERGE (d)-[:RECORDED_IN]->(po)
MERGE (d)-[:ANNOUNCED_BY]->(a)
SET d.at = coalesce(d.at, po.created)
```

### `LINK_DECISION_THREAD`

```cypher
MATCH (d:Decision)-[:DECIDES]->(:PEP {id: $pep_id})
WHERE d.kind IN ['accept', 'reject']
MATCH (t:Thread {id: $thread_id})
MERGE (d)-[:RECORDED_IN]->(t)
```

## Ingest: GitHub (revealed ownership, implementing PRs)

### `UPSERT_COMMITTED`

Person -[:COMMITTED_TO {count, last_at}]-> Area: who actually works on it (last 12 months).

```cypher
UNWIND $rows AS r
MERGE (a:Area {id: r.area_id})
ON CREATE SET a.name = r.area
MERGE (p:Person {id: r.person_id})
ON CREATE SET p.github = r.github
MERGE (p)-[c:COMMITTED_TO]->(a)
SET c.count = r.count, c.last_at = date(r.last_at), c.dates = r.dates
```

### `UPSERT_PRS`

Merged PR whose title names a PEP -[:IMPLEMENTS]-> that PEP.

```cypher
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
```

## Derived edges

### `CO_AUTHOR_PAIRS`

People who co-wrote a PEP (weight 3 per shared PEP).

```cypher
MATCH (a:Person)-[:AUTHORED]->(p:PEP)<-[:AUTHORED]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT p) AS n
```

### `THREAD_POSTERS`

Distinct posters per thread (pairs are built in Python to avoid a post×post blow-up).

```cypher
MATCH (a:Person)-[:POSTED]->(:Post)-[:IN]->(t:Thread)
RETURN t.id AS t, collect(DISTINCT a.id) AS people
```

### `CO_AREA_PAIRS`

People committing to the same area (weight 2 per shared area).

```cypher
MATCH (a:Person)-[:COMMITTED_TO]->(ar:Area)<-[:COMMITTED_TO]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT ar) AS n
```

### `UPSERT_COLLABORATED`

Stored once per pair (lower id → higher id); weight is recomputed, so re-runs are safe.

```cypher
UNWIND $rows AS r
MATCH (a:Person {id: r.a}), (b:Person {id: r.b})
MERGE (a)-[c:COLLABORATED]->(b)
SET c.weight = r.w
```

### `AREAS`

```cypher
MATCH (a:Area) RETURN a.id AS id, a.name AS name, a.kind AS kind
```

### `PEP_TITLES`

```cypher
MATCH (p:PEP) RETURN p.id AS id, p.title AS title
```

### `CHUNKS_MENTIONING`

Full-text search over PEP text chunks for one area name.

```cypher
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node
MATCH (node)-[:PART_OF]->(p:PEP)
RETURN p.id AS pep, node.text AS text
```

### `UPSERT_CONCERNS`

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep}), (a:Area {id: r.area})
MERGE (p)-[:CONCERNS]->(a)
```

### `PAGERANK_PEPS`

Influence of each PEP in the citation graph, stored for search re-ranking.

```cypher
CALL algo.pageRank('PEP', 'REFERENCES') YIELD node, score
SET node.pagerank = score
```

## Replayable change events

### `UPSERT_EVENT`

```cypher
MERGE (e:Event {id: $id})
ON CREATE SET e.applied = true
SET e.kind = $kind, e.at = date($at), e.summary = $summary, e.source_url = $source_url, e.payload_json = $payload
WITH e
MATCH (p:PEP {id: $pep_id})
MERGE (e)-[:AFFECTS]->(p)
```

### `EVENT_SET_STATUS`

```cypher
MATCH (p:PEP {id: $pep_id}) SET p.status = $status
```

### `EVENT_DELETE_SUPERSEDES`

```cypher
MATCH (n:PEP)-[r:SUPERSEDES]->(:PEP {id: $pep_id})
WHERE n.id IN $by
DELETE r
```

### `EVENT_DELETE_DECISION`

```cypher
MATCH (d:Decision {id: $decision_id}) DELETE d
```

### `EVENT_ADD_SUPERSEDES`

```cypher
UNWIND $by AS newer
MATCH (n:PEP {id: newer}), (p:PEP {id: $pep_id})
MERGE (n)-[:SUPERSEDES]->(p)
```

### `EVENT_ADD_DECISION`

```cypher
MATCH (p:PEP {id: $pep_id})
MERGE (d:Decision {id: $decision_id})
SET d.kind = 'supersede', d.at = date($at), d.source_url = $source_url, d.summary = $summary
MERGE (d)-[:DECIDES]->(p)
```

### `EVENT_SET_APPLIED`

```cypher
MATCH (e:Event {id: $id}) SET e.applied = $applied
```

## Retrieval

### `VECTOR_CHUNKS`

```cypher
CALL db.idx.vector.queryNodes('Chunk', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
```

### `VECTOR_POSTS`

```cypher
CALL db.idx.vector.queryNodes('Post', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:IN]->(:Thread)<-[:DISCUSSED_IN]-(p:PEP)
WHERE $as_of IS NULL OR (node.created <= date($as_of) AND (p.created IS NULL OR p.created <= date($as_of)))
RETURN node.id AS id, 'Post' AS label, 'Discussion' AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, node.source_url AS url, p.pagerank AS pagerank
```

### `FULLTEXT_CHUNKS`

```cypher
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS ft,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
LIMIT $k
```

### `FULLTEXT_PEP_TITLES`

```cypher
CALL db.idx.fulltext.queryNodes('PEP', $q) YIELD node, score
WHERE $as_of IS NULL OR node.created IS NULL OR node.created <= date($as_of)
RETURN node.id AS id, 'PEP' AS label, 'Title' AS heading, node.title AS text, score AS ft,
       node.id AS pep_id, node.title AS title, node.number AS number, node.source_url AS url, node.pagerank AS pagerank
LIMIT $k
```

## Agent tools (each returns rows of src/rel/dst "triples")

### `PEP_NODE`

```cypher
MATCH (p:PEP {id: $id}) RETURN properties(p) AS p
```

### `INTO_PEP`

Who/what points at the PEP: decisions, authors, delegates, implementing PRs, events.

```cypher
MATCH (a)-[r:DECIDES|AUTHORED|DELEGATE_FOR|IMPLEMENTS|AFFECTS]->(b:PEP {id: $id})
WHERE NOT a:Event OR coalesce(a.applied, true) = true   // replay events stay hidden until applied

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 100
```

### `DECISION_PROVENANCE`

Where each decision was recorded and who announced it.

```cypher
MATCH (:PEP {id: $id})<-[:DECIDES]-(a:Decision)-[r:RECORDED_IN|ANNOUNCED_BY]->(b)

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
```

### `SUPERSEDE_CHAIN`

The supersede chain in both directions, up to 3 hops.

```cypher
MATCH path = (:PEP {id: $id})-[:SUPERSEDES*1..3]-(:PEP)
UNWIND relationships(path) AS r
WITH DISTINCT r
WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
```

### `PEP_THREADS`

```cypher
MATCH (a:PEP {id: $id})-[r:DISCUSSED_IN]->(b:Thread)

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 10
```

### `RELATED_1`

Neighbourhood over citation/supersede/require links (hop count fixed per query).

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..1]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

### `RELATED_2`

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..2]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

### `RELATED_3`

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..3]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

### `FIND_AREA`

```cypher
MATCH (a:Area)
WHERE toLower(a.name) = toLower($t) OR toLower(a.name) CONTAINS toLower($t)
RETURN a.id AS id, a.name AS name, toLower(a.name) = toLower($t) AS exact
ORDER BY exact DESC, size(a.name) ASC
LIMIT 1
```

### `AREA_EXPERTS`

Declared (Experts Index) and revealed (commits) owners of one area.

```cypher
MATCH (a:Person)-[r:EXPERT_IN|COMMITTED_TO]->(b:Area {id: $id})

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
```

## Agent memory (one graph per agent)

### `CREATE_ANSWER`

```cypher
CREATE (a:Answer {id: $id, question: $question, text: $text, created_at: $now, as_of: $as_of, stale: false})
```

### `LINK_EVIDENCE`

```cypher
MATCH (x {id: $src})
UNWIND $refs AS ref
MERGE (e:Evidence {ref: ref})
ON CREATE SET e.id = 'ev:' + ref, e.ref_label = split(ref, ':')[0]
MERGE (x)-[:DERIVED_FROM]->(e)
```

### `CREATE_BELIEFS`

```cypher
MATCH (a:Answer {id: $answer_id})
UNWIND $beliefs AS b
CREATE (bl:Belief {id: b.id, text: b.text, status: b.status, confidence: b.confidence, created_at: $now, stale: false})
MERGE (a)-[:DERIVED_FROM]->(bl)
```

### `LIST_BELIEFS`

```cypher
MATCH (b:Belief)
WHERE $status IS NULL OR b.status = $status
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence,
       b.stale AS stale, b.stale_because AS stale_because, b.created_at AS created_at
ORDER BY b.created_at
```

### `CREATE_ACTION`

```cypher
CREATE (x:Action {id: $id, kind: $kind, payload_json: $payload, status: 'pending', created_at: $now})
WITH x
UNWIND $derived_from AS ref
MATCH (y) WHERE (y:Answer OR y:Belief) AND y.id = ref
MERGE (x)-[:DERIVED_FROM]->(y)
```

## User memory (one graph per user)

### `CREATE_EPISODE`

```cypher
CREATE (e:Episode {id: $id, question: $question, answer_id: $answer_id, at: $now})
WITH e
UNWIND $areas AS ref
MERGE (i:Interest {area_ref: ref})
ON CREATE SET i.weight = 0
SET i.weight = i.weight + 1, i.last_at = $now
MERGE (e)-[:SUGGESTS]->(i)
```

### `EXPLAIN_INTEREST`

```cypher
MATCH (e:Episode)-[r:SUGGESTS]->(i:Interest {area_ref: $area})
RETURN e.id AS eid, e.question AS q, e.at AS at, i.area_ref AS area, i.weight AS w
ORDER BY e.at
```

### `FORGET_DECREMENT`

```cypher
MATCH (:Episode {id: $id})-[:SUGGESTS]->(i:Interest) SET i.weight = i.weight - 1
```

### `FORGET_EPISODE`

```cypher
MATCH (e:Episode {id: $id}) DELETE e
```

### `DROP_EMPTY_INTERESTS`

```cypher
MATCH (i:Interest) WHERE i.weight <= 0 DELETE i
```

### `LIST_INTERESTS`

```cypher
MATCH (i:Interest) RETURN i.area_ref AS area, i.weight AS weight, i.last_at AS last_at ORDER BY weight DESC
```

### `AREAS_OF_PEPS`

Areas touched by a set of cited PEPs (for per-user interest memory).

```cypher
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN DISTINCT a.id AS id
```

## Steward: staleness ripple

### `SUPERSEDERS`

```cypher
MATCH (s:PEP)-[:SUPERSEDES]->(c:PEP)
WHERE c.id IN $changed
RETURN DISTINCT s.id AS id
```

### `RIPPLE_SOFT_1`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..1]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

### `RIPPLE_SOFT_2`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..2]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

### `RIPPLE_SOFT_3`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..3]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

### `MARK_PEPS_STALE`

```cypher
MATCH (p:PEP) WHERE p.id IN $ids SET p.stale = true, p.stale_because = $reason
```

### `MARK_CHUNKS_STALE`

```cypher
MATCH (ch:Chunk)-[:PART_OF]->(p:PEP)
WHERE p.id IN $ids
SET ch.stale = true, ch.stale_because = $reason
RETURN ch.id AS id
```

### `RIPPLE_EDGES`

```cypher
MATCH (a:PEP)-[r:REFERENCES|REQUIRES|SUPERSEDES]->(b:PEP)
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS s, 'PEP' AS sl, {number: a.number, title: a.title, stale: a.stale} AS sp, type(r) AS t, {} AS rp,
       b.id AS d, 'PEP' AS dl, {number: b.number, title: b.title, stale: b.stale} AS dp
```

### `CLEAR_STALE`

```cypher
MATCH (n) WHERE n.stale = true SET n.stale = false, n.stale_because = null
```

## Steward: fan-out into an agent's memory graph

### `DEPENDENTS_OF_EVIDENCE`

Everything an agent built on the changed evidence (walks DERIVED_FROM upward).

```cypher
MATCH (e:Evidence) WHERE e.ref IN $refs
SET e.stale = true, e.stale_because = $reason
WITH e
MATCH (x)-[:DERIVED_FROM*1..5]->(e)
WHERE x:Belief OR x:Answer OR x:Action
RETURN DISTINCT x.id AS id, labels(x)[0] AS label, x.status AS status
```

### `MARK_BELIEFS_STALE`

```cypher
MATCH (b:Belief) WHERE b.id IN $ids AND b.status <> 'stale'
SET b.prev_status = b.status, b.status = 'stale', b.stale = true, b.stale_because = $reason
```

### `MARK_ANSWERS_STALE`

```cypher
MATCH (a:Answer) WHERE a.id IN $ids SET a.stale = true, a.stale_because = $reason
```

### `BLOCK_ACTIONS`

```cypher
MATCH (x:Action) WHERE x.id IN $ids AND x.status = 'pending'
SET x.status = 'blocked', x.blocked_by_steward = true, x.reason = $reason
RETURN x.id AS id
```

### `RESTORE_BELIEFS`

Undo of a change event inside an agent graph: put beliefs/actions back as they were.

```cypher
MATCH (b:Belief) WHERE b.prev_status IS NOT NULL
SET b.status = b.prev_status, b.prev_status = null, b.stale = false, b.stale_because = null
```

### `RESTORE_ACTIONS`

```cypher
MATCH (x:Action) WHERE x.blocked_by_steward = true AND x.status = 'blocked'
SET x.status = 'pending', x.reason = null, x.blocked_by_steward = null
```

## Action gate

### `GATE_OFFENDING_PATH`

An action may run only if nothing it was derived from is stale or tentative.

```cypher
MATCH p = (a:Action {id: $id})-[:DERIVED_FROM*1..5]->(x)
WHERE x.stale = true OR (x:Belief AND x.status = 'tentative')
RETURN [n IN nodes(p) | n.id] AS path, x.stale AS stale, x.status AS status,
       coalesce(x.stale_because, '') AS why, coalesce(x.ref, x.id) AS culprit
LIMIT 1
```

### `ACTION_NODE`

```cypher
MATCH (x:Action {id: $id}) RETURN x.status AS status, x.kind AS kind, x.payload_json AS payload
```

### `EXECUTE_ACTION`

```cypher
MATCH (x:Action {id: $id})
SET x.status = 'done', x.done_at = $now
CREATE (o:Outbox {id: $oid, action_id: $id, kind: x.kind, payload_json: x.payload_json, at: $now})
RETURN o.id AS id
```

### `SET_ACTION_BLOCKED`

```cypher
MATCH (x:Action {id: $id}) SET x.status = 'blocked', x.reason = $reason
```

### `GATE_ROOT_CAUSE_PATH`

Root cause first: the longest chain down to a stale Evidence stub.

```cypher
MATCH p = (a:Action {id: $id})-[:DERIVED_FROM*1..5]->(e:Evidence)
WHERE e.stale = true
RETURN [n IN nodes(p) | n.id] AS path, true AS stale, null AS status,
       coalesce(e.stale_because, '') AS why, e.ref AS culprit
ORDER BY length(p) DESC
LIMIT 1
```

## Shared coordination board (lineage:shared)

### `UPSERT_FIX_TASKS`

```cypher
UNWIND $rows AS r
MERGE (t:FixTask {id: r.id})
ON CREATE SET t.status = 'open', t.created_at = $now, t.kind = r.kind, t.target_ref = r.target_ref,
              t.reason = r.reason, t.suggested = r.suggested, t.event = r.event
RETURN t.id AS id
```

### `CLAIM_NEXT`

Atomic claim. One query = one atomic unit, and FalkorDB serialises writes per graph, so two agents can never claim the same task (no locks needed).

```cypher
MATCH (t:FixTask)
WHERE t.status = 'open' OR (t.status = 'claimed' AND t.claim_until <= $now)
WITH t ORDER BY t.created_at, t.id LIMIT 1
SET t.status = 'claimed', t.claimed_by = $agent, t.claim_until = $until
MERGE (a:Agent {name: $agent})
MERGE (a)-[c:CLAIMED]->(t)
SET c.until = $until
RETURN t.id AS id, t.kind AS kind, t.target_ref AS target_ref, t.reason AS reason, t.suggested AS suggested
```

### `COMPLETE_TASK`

```cypher
MATCH (t:FixTask {id: $id})
WHERE t.claimed_by = $agent AND t.status = 'claimed'
SET t.status = 'done', t.done_at = $now
RETURN t.id AS id
```

### `LIST_TASKS`

```cypher
MATCH (t:FixTask)
WHERE $status IS NULL OR t.status = $status
RETURN t.id AS id, t.kind AS kind, t.target_ref AS target_ref, t.reason AS reason, t.status AS status,
       t.claimed_by AS claimed_by, t.suggested AS suggested, t.created_at AS created_at
ORDER BY t.created_at, t.id
```

### `AREA_OWNERS_OF_PEPS`

Who should review a PEP: active listed experts of the areas it concerns.

```cypher
MATCH (p:PEP)-[:CONCERNS]->(:Area)<-[e:EXPERT_IN]-(x:Person)
WHERE p.id IN $ids AND (e.inactive IS NULL OR e.inactive = false)
RETURN p.id AS pep, p.title AS title, collect(DISTINCT coalesce(x.github, x.name)) AS owners
```

## Ownership drift: declared (Experts Index) vs revealed (commits)

### `TRACKED_AREAS`

```cypher
MATCH (:Person)-[:COMMITTED_TO]->(a:Area) RETURN DISTINCT a.id AS id
```

### `DRIFT_DECLARED`

```cypher
MATCH (p:Person)-[e:EXPERT_IN]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, coalesce(e.inactive, false) AS inactive
```

### `DRIFT_REVEALED`

```cypher
MATCH (p:Person)-[c:COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, c.count AS commits, c.last_at AS last_at
```

### `AREA_NAMES`

```cypher
MATCH (a:Area) WHERE a.id IN $areas RETURN a.id AS id, a.name AS name
```

## What-if (runs on a GRAPH.COPY fork)

### `PERSON_EXISTS`

```cypher
MATCH (p:Person {id: $id}) RETURN p.id AS id, coalesce(p.name, p.github) AS name
```

### `COLLAB_COMPONENTS`

Collaboration clusters (size >= 2) via weakly connected components.

```cypher
CALL algo.WCC({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATED']}) YIELD node, componentId
WITH componentId, count(node) AS size
WHERE size >= 2
RETURN count(componentId) AS n
```

### `ACTIVE_IN_AREAS`

Areas where someone is "active": listed and not inactive, or >= 3 commits.

```cypher
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas AND ((type(r) = 'EXPERT_IN' AND coalesce(r.inactive, false) = false)
                          OR (type(r) = 'COMMITTED_TO' AND r.count >= 3))
RETURN a.id AS id, a.name AS name, count(DISTINCT p) AS n
```

### `AREAS_OF_PERSON`

```cypher
MATCH (:Person {id: $id})-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
RETURN DISTINCT a.id AS id
```

### `DELETE_PERSON`

```cypher
MATCH (p:Person {id: $id}) DELETE p
```

### `TOP_COLLABORATORS`

```cypher
MATCH (:Person {id: $id})-[c:COLLABORATED]-(y:Person)
RETURN coalesce(y.name, y.github, y.id) AS who, c.weight AS w
ORDER BY w DESC LIMIT 5
```

### `AREA_COMMITTERS`

```cypher
MATCH (y:Person)-[c:COMMITTED_TO]->(a:Area {id: $area})
WHERE y.id <> $id
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, c.count AS n
ORDER BY n DESC LIMIT 3
```

### `PERSON_FOOTPRINT`

```cypher
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH p, count(DISTINCT pep) AS authored
OPTIONAL MATCH (d:Decision)-[:ANNOUNCED_BY]->(p)
RETURN authored, count(DISTINCT d) AS announced
```

## API listings

### `LIST_EVENTS`

```cypher
MATCH (e:Event)-[:AFFECTS]->(p:PEP)
RETURN e.id AS id, e.kind AS kind, e.summary AS summary, toString(e.at) AS at, e.applied AS applied,
       e.source_url AS source_url, p.id AS pep, e.payload_json AS payload
ORDER BY at
```

### `LIST_ACTIONS`

```cypher
MATCH (x:Action)
RETURN x.id AS id, x.kind AS kind, x.status AS status, x.reason AS reason, x.payload_json AS payload, x.created_at AS created_at
ORDER BY x.created_at
```

### `SEARCH_PEOPLE`

```cypher
MATCH (p:Person)
WHERE toLower(coalesce(p.name, '')) CONTAINS toLower($q) OR toLower(coalesce(p.github, '')) CONTAINS toLower($q)
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
RETURN p.id AS id, p.name AS name, p.github AS github, count(pep) AS peps
ORDER BY peps DESC, id LIMIT 15
```

## Index card for one node

### `CARD_BY_LABEL`

```cypher
MATCH (n:PEP {id: $id})
OPTIONAL MATCH (n)-[r]-(m)
WITH n, r, m LIMIT 60
RETURN properties(n) AS props, type(r) AS rel, startNode(r).id = n.id AS outgoing, m.id AS mid, labels(m)[0] AS ml,
       coalesce(m.title, m.name, m.github, m.kind, m.heading) AS mname
```

### `BELIEFS_ON_REF`

```cypher
MATCH (b:Belief)-[:DERIVED_FROM]->(:Evidence {ref: $ref})
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence
```

### `DELETE_CONCERNS`

```cypher
MATCH (:PEP)-[r:CONCERNS]->(:Area) DELETE r
```

### `AREAS_NAMED_IN`

Graph-only backend: which known module names appear in a question.

```cypher
MATCH (a:Area)
WHERE size(a.name) >= 4 AND toLower($q) CONTAINS toLower(a.name)
RETURN a.name AS name
ORDER BY size(a.name) DESC
LIMIT 1
```

## Algorithms as agent tools

### `RESOLVE_PERSON`

```cypher
MATCH (p:Person)
WHERE toLower(p.name) = toLower($q) OR toLower(p.github) = toLower($q)
   OR toLower(p.name) CONTAINS toLower($q)
RETURN p.id AS id, (toLower(coalesce(p.name, '')) = toLower($q) OR toLower(coalesce(p.github, '')) = toLower($q)) AS exact
ORDER BY exact DESC LIMIT 1
```

### `RESOLVE_AREA`

```cypher
MATCH (a:Area) WHERE toLower(a.name) = toLower($q) RETURN a.id AS id LIMIT 1
```

### `BETWEENNESS_PEOPLE`

Who bridges otherwise separate groups of collaborators. Runs on TIE (two-way copies of COLLABORATED): FalkorDB's betweenness follows edge direction, and collaboration has none.

```cypher
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['TIE']}) YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC
```

### `PEP_COMMUNITIES`

Topic clusters in the proposal citation graph (community detection via label propagation).

```cypher
CALL algo.labelPropagation({nodeLabels: ['PEP'], relationshipTypes: ['REFERENCES', 'REQUIRES', 'SUPERSEDES']}) YIELD node, communityId
WITH communityId, collect(node) AS ps
WHERE size(ps) >= $min
RETURN communityId AS cid, size(ps) AS size,
       [p IN ps | {id: p.id, number: p.number, title: p.title, pagerank: coalesce(p.pagerank, 0.0)}] AS members
ORDER BY size DESC
```

### `AREA_COUNTS_FOR_PEPS`

```cypher
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN a.name AS area, count(p) AS n
ORDER BY n DESC LIMIT 4
```

### `MATERIALIZE_TIES`

Two-way TIE edges for direction-sensitive algorithms (betweenness).

```cypher
MATCH (a:Person)-[c:COLLABORATED]->(b:Person)
MERGE (a)-[t1:TIE]->(b) SET t1.weight = c.weight, t1.cost = 1.0 / c.weight
MERGE (b)-[t2:TIE]->(a) SET t2.weight = c.weight, t2.cost = 1.0 / c.weight
```

### `DELETE_TASKS_OF_EVENT`

Undo of a change event on the shared board: drop the review tasks it opened.

```cypher
MATCH (t:FixTask) WHERE t.event = $event DELETE t
```

## What-if, generalised: groups of people; previews of reversing a proposal

### `PERSONS_EXIST`

```cypher
MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, coalesce(p.name, p.github, p.id) AS name
```

### `AREAS_OF_PEOPLE`

```cypher
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area) WHERE p.id IN $ids RETURN DISTINCT a.id AS id
```

### `DELETE_PEOPLE`

```cypher
MATCH (p:Person) WHERE p.id IN $ids DELETE p
```

### `TOP_COLLABORATORS_OF_GROUP`

```cypher
MATCH (x:Person)-[c:COLLABORATED]-(y:Person)
WHERE x.id IN $ids AND NOT y.id IN $ids
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, sum(c.weight) AS w
ORDER BY w DESC LIMIT 5
```

### `AREA_COMMITTERS_EXCEPT`

```cypher
MATCH (y:Person)-[c:COMMITTED_TO]->(a:Area {id: $area})
WHERE NOT y.id IN $ids
RETURN y.id AS id, coalesce(y.name, y.github, y.id) AS who, c.count AS n
ORDER BY n DESC LIMIT 3
```

### `GROUP_FOOTPRINT`

```cypher
MATCH (p:Person) WHERE p.id IN $ids
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH collect(DISTINCT pep) AS peps
OPTIONAL MATCH (d:Decision)-[:ANNOUNCED_BY]->(q:Person) WHERE q.id IN $ids
RETURN size(peps) AS authored, count(DISTINCT d) AS announced
```

### `SEARCH_PEOPLE_RANKED`

People search: names/handles that START with the text first, then word starts, then anywhere.

```cypher
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
```

### `SEARCH_PEPS`

```cypher
MATCH (p:PEP)
WHERE toString(p.number) STARTS WITH $q OR toLower(p.title) CONTAINS toLower($q)
RETURN p.id AS id, p.number AS number, p.title AS title, p.status AS status
ORDER BY CASE WHEN toString(p.number) = $q THEN 0 ELSE 1 END, coalesce(p.pagerank, 0) DESC
LIMIT 8
```

### `PEP_BRIEFS`

```cypher
MATCH (p:PEP) WHERE p.id IN $ids
RETURN p.id AS id, p.number AS number, p.title AS title, p.status AS status, toString(p.created) AS created
ORDER BY coalesce(p.pagerank, 0) DESC
```

### `DEPENDENT_RELATIONS`

How each dependent rests on the reversed proposal (what-if preview).

```cypher
MATCH (d:PEP)-[r:REFERENCES|REQUIRES]->(:PEP {id: $pid})
WHERE d.id IN $ids
RETURN d.id AS id, type(r) AS rel
```

### `DEPENDENT_ANSWERS`

The agent's current answers that rest on any of these refs (read-only, for the preview graph).

```cypher
MATCH (e:Evidence) WHERE e.ref IN $refs
MATCH (a:Answer)-[:DERIVED_FROM*1..5]->(e)
WHERE coalesce(a.stale, false) = false
RETURN DISTINCT a.id AS id, a.text AS text, e.ref AS ref
```

### `PEOPLE_AREA_LINKS`

Who left, and how they were tied to the modules their leaving affects (departure what-if graph).

```cypher
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
WHERE p.id IN $ids AND a.id IN $areas
RETURN DISTINCT p.id AS p, type(r) AS t, a.id AS a
```

### `CHUNKS_OF_PEPS`

```cypher
MATCH (c:Chunk)-[:PART_OF]->(p:PEP) WHERE p.id IN $ids RETURN c.id AS id
```

### `DEPENDENTS_PREVIEW`

Read-only twin of DEPENDENTS_OF_EVIDENCE: what an agent built on these ids (nothing is marked).

```cypher
MATCH (e:Evidence) WHERE e.ref IN $refs
MATCH (x)-[:DERIVED_FROM*1..5]->(e)
WHERE (x:Belief AND x.status <> 'stale') OR (x:Answer AND coalesce(x.stale, false) = false) OR (x:Action AND x.status = 'pending')
RETURN labels(x)[0] AS label, count(DISTINCT x) AS n
```

## Explaining a missing answer (lineage/graph/miss.py)

### `PEP_BRIEF`

```cypher
MATCH (p:PEP {number: $n}) RETURN p.number AS number, p.title AS title, p.status AS status, toString(p.created) AS created
```

### `NEAREST_PEPS`

```cypher
MATCH (p:PEP)
RETURN p.number AS number, p.title AS title
ORDER BY abs(p.number - $n), p.number
LIMIT 2
```

### `FIRST_PEP_ABOUT`

```cypher
MATCH (p:PEP)
WHERE toLower(p.title) CONTAINS toLower($name)
RETURN p.number AS number, toString(p.created) AS created
ORDER BY p.created LIMIT 1
```

### `FIRST_PEP_CONCERNING`

```cypher
MATCH (p:PEP)-[:CONCERNS]->(:Area {name: $name})
RETURN p.number AS number, toString(p.created) AS created
ORDER BY p.created LIMIT 1
```

### `EXAMPLE_PEP_AT`

```cypher
MATCH (p:PEP)
WHERE $as_of IS NULL OR p.created <= date($as_of)
RETURN p.number AS number
ORDER BY coalesce(p.pagerank, 0) DESC LIMIT 1
```

## Real effects of gated actions (lineage/memory/effects.py)

### `ACTION_ANSWER`

```cypher
MATCH (x:Action {id: $id})-[:DERIVED_FROM]->(a:Answer)
OPTIONAL MATCH (a)-[:DERIVED_FROM]->(e:Evidence)
RETURN a.id AS id, a.question AS question, a.text AS text, collect(DISTINCT e.ref) AS refs
```

### `PUBLISH_FAQ`

```cypher
MERGE (f:FaqEntry {id: $id})
SET f.answer_id = $answer_id, f.question = $question, f.answer = $answer, f.refs = $refs,
    f.status = 'live', f.published_at = $now, f.withdrawn_reason = null, f.withdrawn_event = null
RETURN f.id AS id
```

### `LIST_FAQ`

```cypher
MATCH (f:FaqEntry)
RETURN f.id AS id, f.question AS question, f.answer AS answer, f.refs AS refs, f.status AS status,
       f.published_at AS published_at, f.withdrawn_reason AS withdrawn_reason, f.withdrawn_at AS withdrawn_at
ORDER BY f.published_at DESC
```

### `WITHDRAW_FAQ`

```cypher
MATCH (f:FaqEntry) WHERE f.answer_id IN $answer_ids AND f.status = 'live'
SET f.status = 'withdrawn', f.withdrawn_reason = $reason, f.withdrawn_event = $event, f.withdrawn_at = $now
RETURN count(f) AS n
```

### `RESTORE_FAQ`

```cypher
MATCH (f:FaqEntry {withdrawn_event: $event})
SET f.status = 'live', f.withdrawn_reason = null, f.withdrawn_event = null, f.withdrawn_at = null
```

## "Can I rely on this?" for outside agents

### `RELY_COMPANY`

```cypher
MATCH (n) WHERE n.id IN $ids
OPTIONAL MATCH (s:PEP)-[:SUPERSEDES]->(n)
RETURN n.id AS id, labels(n)[0] AS label, n.status AS status, coalesce(n.stale, false) AS stale,
       n.stale_because AS why, collect(s.id) AS replaced_by
```

### `RELY_AGENT`

```cypher
MATCH (n) WHERE n.id IN $ids AND (n:Answer OR n:Belief)
RETURN n.id AS id, coalesce(n.stale, false) OR coalesce(n.status, '') = 'stale' AS stale, n.stale_because AS why
```

## Ownership v2: recency-weighted knowledge, truck factor, introductions

### `AREA_RECENCY`

lineage.recency is a JavaScript UDF (lineage/graph/udf.py): each commit counts 0.5^(age / half-life).

```cypher
MATCH (p:Person)-[c:COMMITTED_TO]->(a:Area)
WHERE c.dates IS NOT NULL AND ($areas IS NULL OR a.id IN $areas)
RETURN a.id AS area_id, a.name AS area, p.id AS id, coalesce(p.name, p.github, p.id) AS name,
       lineage.recency(c.dates, $as_of, $half_life) AS score, lineage.in_window(c.dates, $since, $as_of) AS commits
```

### `INTRO_PATH`

Weighted shortest path through two-way collaboration ties; cost = 1/weight, so strong ties are cheap.

```cypher
MATCH (a:Person {id: $src}), (b:Person {id: $dst})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['TIE'], weightProp: 'cost', maxLen: 6, pathCount: 1})
YIELD path, pathWeight
RETURN [n IN nodes(path) | {id: n.id, name: coalesce(n.name, n.github, n.id)}] AS people,
       [r IN relationships(path) | r.weight] AS weights, pathWeight AS cost
```
