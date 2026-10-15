# Cypher queries

Every query Lineage depends on, generated from `lineage/graph/queries.py`. Writes use `UNWIND $rows` + `MERGE` on stable ids, so ingestion is batched and safe to re-run. Plans come from `GRAPH.EXPLAIN` on the real graph.

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

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (p:PEP), 
            Unwind
            Filter
                Include Pending | (p:PEP)
                    Node By Index Scan | (p:PEP)
                        Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_0:AUTHORED]->(p), 
        Filter
            Node By Index Scan | (p:PEP)
                Project
                    Commit
                        Merge | (a:Person), 
                            Unwind
                            Filter
                                Include Pending | (a:Person)
                                    Node By Index Scan | (a:Person)
                                        Argument
        Expand Into | (a)->(p:PEP)
            Argument
```
</details>

### `UPSERT_SUPERSEDES`

New PEP -[:SUPERSEDES]-> old PEP (from superseded_by / replaces).

```cypher
UNWIND $rows AS r
MATCH (n:PEP {id: r.src}), (o:PEP {id: r.dst})
MERGE (n)-[:SUPERSEDES]->(o)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (n)-[_anon_0:SUPERSEDES]->(o), 
        Apply
            Unwind
            Cartesian Product
                Filter
                    Node By Index Scan | (n:PEP)
                        Argument
                Filter
                    Node By Index Scan | (o:PEP)
                        Argument
        Expand Into | (n)->(o:PEP)
            Argument
```
</details>

### `UPSERT_REQUIRES`

PEP -[:REQUIRES]-> PEP it depends on.

```cypher
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[:REQUIRES]->(b)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_0:REQUIRES]->(b), 
        Apply
            Unwind
            Cartesian Product
                Filter
                    Node By Index Scan | (a:PEP)
                        Argument
                Filter
                    Node By Index Scan | (b:PEP)
                        Argument
        Expand Into | (a)->(b:PEP)
            Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (d)-[_anon_0:DECIDES]->(p), 
        Update
            Merge | (d:Decision), 
                Filter
                    Node By Index Scan | (p:PEP)
                        Unwind
                Filter
                    Include Pending | (d:Decision)
                        Node By Index Scan | (d:Decision)
                            Argument
        Expand Into | (d)->(p:PEP)
            Argument
```
</details>

## Ingest: people (after identity resolution)

### `UPSERT_PEOPLE`

Write each resolved person's name and handles; aliases is a list of strings.

```cypher
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = coalesce(r.name, p.name), p.github = r.github, p.discourse = r.discourse, p.aliases = r.aliases
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (p:Person), 
            Unwind
            Filter
                Include Pending | (p:Person)
                    Node By Index Scan | (p:Person)
                        Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (c)-[_anon_0:PART_OF]->(p), 
        Update
            Merge | (c:Chunk), 
                Filter
                    Node By Index Scan | (p:PEP)
                        Unwind
                Filter
                    Include Pending | (c:Chunk)
                        Node By Index Scan | (c:Chunk)
                            Argument
        Expand Into | (c)->(p:PEP)
            Argument
```
</details>

### `UPSERT_REFERENCES`

PEP text mentions another PEP ("PEP 563", :pep:`563`). Only known PEPs are linked.

```cypher
UNWIND $rows AS r
MATCH (a:PEP {id: r.src}), (b:PEP {id: r.dst})
MERGE (a)-[x:REFERENCES]->(b)
SET x.count = r.count
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (a)-[x:REFERENCES]->(b), 
            Apply
                Unwind
                Cartesian Product
                    Filter
                        Node By Index Scan | (a:PEP)
                            Argument
                    Filter
                        Node By Index Scan | (b:PEP)
                            Argument
            Expand Into | (a)-[x:REFERENCES]->(b:PEP)
                Argument
```
</details>

### `UPSERT_DELEGATES`

The PEP-Delegate header: who was given authority to decide the PEP.

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id})
MERGE (a:Person {id: r.person_id})
ON CREATE SET a.name = r.name
MERGE (a)-[:DELEGATE_FOR]->(p)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_0:DELEGATE_FOR]->(p), 
        Merge | (a:Person), 
            Filter
                Node By Index Scan | (p:PEP)
                    Unwind
            Filter
                Include Pending | (a:Person)
                    Node By Index Scan | (a:Person)
                        Argument
        Expand Into | (a)->(p:PEP)
            Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (p)-[e:EXPERT_IN]->(a), 
            Merge | (p:Person), 
                Update
                    Merge | (a:Area), 
                        Unwind
                        Filter
                            Include Pending | (a:Area)
                                Node By Index Scan | (a:Area)
                                    Argument
                Filter
                    Include Pending | (p:Person)
                        Node By Index Scan | (p:Person)
                            Argument
            Expand Into | (p)-[e:EXPERT_IN]->(a:Area)
                Argument
```
</details>

## Ingest: discuss.python.org

### `UPSERT_THREAD`

```cypher
MERGE (t:Thread {id: $id})
SET t.title = $title, t.created = date($date), t.posts_count = $posts_count, t.source_url = $url
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (t:Thread), 
            Filter
                Include Pending | (t:Thread)
                    Node By Index Scan | (t:Thread)
                        Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_1:POSTED]->(po), 
        Merge | (a:Person), 
            Project
                Commit
                    Merge | (po)-[_anon_0:IN]->(t), 
                        Filter
                            Node By Index Scan | (t:Thread)
                                Project
                                    Commit
                                        Update
                                            Merge | (po:Post), 
                                                Unwind
                                                Filter
                                                    Include Pending | (po:Post)
                                                        Node By Index Scan | (po:Post)
                                                            Argument
                        Expand Into | (po)->(t:Thread)
                            Argument
            Filter
                Include Pending | (a:Person)
                    Node By Index Scan | (a:Person)
                        Argument
        Expand Into | (a)->(po)
            Argument
```
</details>

### `LINK_PEP_THREAD`

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep_id}), (t:Thread {id: r.thread_id})
MERGE (p)-[:DISCUSSED_IN]->(t)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (p)-[_anon_0:DISCUSSED_IN]->(t), 
        Apply
            Unwind
            Cartesian Product
                Filter
                    Node By Index Scan | (p:PEP)
                        Argument
                Filter
                    Node By Index Scan | (t:Thread)
                        Argument
        Expand Into | (p)->(t:Thread)
            Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (d)-[_anon_4:ANNOUNCED_BY]->(a), 
            Merge | (d)-[_anon_3:RECORDED_IN]->(po), 
                Filter
                    Conditional Traverse | (a)->(po:Post)
                        Filter
                            Conditional Traverse | (d)->(_anon_1:PEP)
                                Filter
                                    Node By Label Scan | (d:Decision)
                Expand Into | (d)->(po:Post)
                    Argument
            Expand Into | (d)->(a:Person)
                Argument
```
</details>

### `LINK_DECISION_THREAD`

```cypher
MATCH (d:Decision)-[:DECIDES]->(:PEP {id: $pep_id})
WHERE d.kind IN ['accept', 'reject']
MATCH (t:Thread {id: $thread_id})
MERGE (d)-[:RECORDED_IN]->(t)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (d)-[_anon_2:RECORDED_IN]->(t), 
        Filter
            Node By Index Scan | (t:Thread)
                Filter
                    Conditional Traverse | (d)->(_anon_1:PEP)
                        Filter
                            Node By Label Scan | (d:Decision)
        Expand Into | (d)->(t:Thread)
            Argument
```
</details>

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
SET c.count = r.count, c.last_at = date(r.last_at)
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (p)-[c:COMMITTED_TO]->(a), 
            Merge | (p:Person), 
                Merge | (a:Area), 
                    Unwind
                    Filter
                        Include Pending | (a:Area)
                            Node By Index Scan | (a:Area)
                                Argument
                Filter
                    Include Pending | (p:Person)
                        Node By Index Scan | (p:Person)
                            Argument
            Expand Into | (p)-[c:COMMITTED_TO]->(a:Area)
                Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_1:AUTHORED_PR]->(pr), 
        Merge | (a:Person), 
            Project
                Commit
                    Merge | (pr)-[_anon_0:IMPLEMENTS]->(pep), 
                        Update
                            Merge | (pr:PR), 
                                Filter
                                    Node By Index Scan | (pep:PEP)
                                        Unwind
                                Filter
                                    Include Pending | (pr:PR)
                                        Node By Index Scan | (pr:PR)
                                            Argument
                        Expand Into | (pr)->(pep:PEP)
                            Argument
            Filter
                Include Pending | (a:Person)
                    Node By Index Scan | (a:Person)
                        Argument
        Expand Into | (a)->(pr:PR)
            Argument
```
</details>

## Derived edges

### `CO_AUTHOR_PAIRS`

People who co-wrote a PEP (weight 3 per shared PEP).

```cypher
MATCH (a:Person)-[:AUTHORED]->(p:PEP)<-[:AUTHORED]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT p) AS n
```

<details><summary>Execution plan</summary>

```
Aggregate
    Filter
        Conditional Traverse | (p)<-(b:Person)
            Conditional Traverse | (a)->(p:PEP)
                Node By Label Scan | (a:Person)
```
</details>

### `THREAD_POSTERS`

Distinct posters per thread (pairs are built in Python to avoid a post×post blow-up).

```cypher
MATCH (a:Person)-[:POSTED]->(:Post)-[:IN]->(t:Thread)
RETURN t.id AS t, collect(DISTINCT a.id) AS people
```

<details><summary>Execution plan</summary>

```
Aggregate
    Conditional Traverse | (_anon_1)<-(a:Person)
        Conditional Traverse | (t)<-(_anon_1:Post)
            Node By Label Scan | (t:Thread)
```
</details>

### `CO_AREA_PAIRS`

People committing to the same area (weight 2 per shared area).

```cypher
MATCH (a:Person)-[:COMMITTED_TO]->(ar:Area)<-[:COMMITTED_TO]-(b:Person)
WHERE a.id < b.id
RETURN a.id AS a, b.id AS b, count(DISTINCT ar) AS n
```

<details><summary>Execution plan</summary>

```
Aggregate
    Filter
        Conditional Traverse | (ar)<-(b:Person)
            Conditional Traverse | (a)->(ar:Area)
                Node By Label Scan | (a:Person)
```
</details>

### `UPSERT_COLLABORATED`

Stored once per pair (lower id → higher id); weight is recomputed, so re-runs are safe.

```cypher
UNWIND $rows AS r
MATCH (a:Person {id: r.a}), (b:Person {id: r.b})
MERGE (a)-[c:COLLABORATED]->(b)
SET c.weight = r.w
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (a)-[c:COLLABORATED]->(b), 
            Apply
                Unwind
                Cartesian Product
                    Filter
                        Node By Index Scan | (a:Person)
                            Argument
                    Filter
                        Node By Index Scan | (b:Person)
                            Argument
            Expand Into | (a)-[c:COLLABORATED]->(b:Person)
                Argument
```
</details>

### `AREAS`

```cypher
MATCH (a:Area) RETURN a.id AS id, a.name AS name, a.kind AS kind
```

<details><summary>Execution plan</summary>

```
Project
    Node By Label Scan | (a:Area)
```
</details>

### `PEP_TITLES`

```cypher
MATCH (p:PEP) RETURN p.id AS id, p.title AS title
```

<details><summary>Execution plan</summary>

```
Project
    Node By Label Scan | (p:PEP)
```
</details>

### `CHUNKS_MENTIONING`

Full-text search over PEP text chunks for one area name.

```cypher
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node
MATCH (node)-[:PART_OF]->(p:PEP)
RETURN p.id AS pep, node.text AS text
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (node)->(p:PEP)
        Node By Fulltext Index Scan
```
</details>

### `UPSERT_CONCERNS`

```cypher
UNWIND $rows AS r
MATCH (p:PEP {id: r.pep}), (a:Area {id: r.area})
MERGE (p)-[:CONCERNS]->(a)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (p)-[_anon_0:CONCERNS]->(a), 
        Apply
            Unwind
            Cartesian Product
                Filter
                    Node By Index Scan | (p:PEP)
                        Argument
                Filter
                    Node By Index Scan | (a:Area)
                        Argument
        Expand Into | (p)->(a:Area)
            Argument
```
</details>

### `PAGERANK_PEPS`

Influence of each PEP in the citation graph, stored for search re-ranking.

```cypher
CALL algo.pageRank('PEP', 'REFERENCES') YIELD node, score
SET node.pagerank = score
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        ProcedureCall
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (e)-[_anon_0:AFFECTS]->(p), 
        Filter
            Node By Index Scan | (p:PEP)
                Project
                    Commit
                        Update
                            Merge | (e:Event), 
                                Filter
                                    Include Pending | (e:Event)
                                        Node By Index Scan | (e:Event)
                                            Argument
        Expand Into | (e)->(p:PEP)
            Argument
```
</details>

### `EVENT_SET_STATUS`

```cypher
MATCH (p:PEP {id: $pep_id}) SET p.status = $status
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Index Scan | (p:PEP)
```
</details>

### `EVENT_DELETE_SUPERSEDES`

```cypher
MATCH (n:PEP)-[r:SUPERSEDES]->(:PEP {id: $pep_id})
WHERE n.id IN $by
DELETE r
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Filter
            Conditional Traverse | (n)-[r:SUPERSEDES]->(_anon_0:PEP)
                Filter
                    Node By Index Scan | (n:PEP)
```
</details>

### `EVENT_DELETE_DECISION`

```cypher
MATCH (d:Decision {id: $decision_id}) DELETE d
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Filter
            Node By Index Scan | (d:Decision)
```
</details>

### `EVENT_ADD_SUPERSEDES`

```cypher
UNWIND $by AS newer
MATCH (n:PEP {id: newer}), (p:PEP {id: $pep_id})
MERGE (n)-[:SUPERSEDES]->(p)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (n)-[_anon_0:SUPERSEDES]->(p), 
        Apply
            Unwind
            Cartesian Product
                Filter
                    Node By Index Scan | (n:PEP)
                        Argument
                Filter
                    Node By Index Scan | (p:PEP)
                        Argument
        Expand Into | (n)->(p:PEP)
            Argument
```
</details>

### `EVENT_ADD_DECISION`

```cypher
MATCH (p:PEP {id: $pep_id})
MERGE (d:Decision {id: $decision_id})
SET d.kind = 'supersede', d.at = date($at), d.source_url = $source_url, d.summary = $summary
MERGE (d)-[:DECIDES]->(p)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (d)-[_anon_0:DECIDES]->(p), 
        Update
            Merge | (d:Decision), 
                Filter
                    Node By Index Scan | (p:PEP)
                Filter
                    Include Pending | (d:Decision)
                        Node By Index Scan | (d:Decision)
                            Argument
        Expand Into | (d)->(p:PEP)
            Argument
```
</details>

### `EVENT_SET_APPLIED`

```cypher
MATCH (e:Event {id: $id}) SET e.applied = $applied
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Index Scan | (e:Event)
```
</details>

## Retrieval

### `VECTOR_CHUNKS`

```cypher
CALL db.idx.vector.queryNodes('Chunk', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Conditional Traverse | (p)<-(node)
            Node By Vector Index Scan
```
</details>

### `VECTOR_POSTS`

```cypher
CALL db.idx.vector.queryNodes('Post', 'emb', $k, vecf32($q)) YIELD node, score
MATCH (node)-[:IN]->(:Thread)<-[:DISCUSSED_IN]-(p:PEP)
WHERE $as_of IS NULL OR (node.created <= date($as_of) AND (p.created IS NULL OR p.created <= date($as_of)))
RETURN node.id AS id, 'Post' AS label, 'Discussion' AS heading, node.text AS text, score AS dist,
       p.id AS pep_id, p.title AS title, p.number AS number, node.source_url AS url, p.pagerank AS pagerank
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Conditional Traverse | (p)->(_anon_1:Thread)
            Conditional Traverse | (node)->(_anon_1:Thread)
                Node By Vector Index Scan
```
</details>

### `FULLTEXT_CHUNKS`

```cypher
CALL db.idx.fulltext.queryNodes('Chunk', $q) YIELD node, score
MATCH (node)-[:PART_OF]->(p:PEP)
WHERE $as_of IS NULL OR p.created IS NULL OR p.created <= date($as_of)
RETURN node.id AS id, 'Chunk' AS label, node.heading AS heading, node.text AS text, score AS ft,
       p.id AS pep_id, p.title AS title, p.number AS number, p.source_url AS url, p.pagerank AS pagerank
LIMIT $k
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Filter
            Conditional Traverse | (p)<-(node)
                Node By Fulltext Index Scan
```
</details>

### `FULLTEXT_PEP_TITLES`

```cypher
CALL db.idx.fulltext.queryNodes('PEP', $q) YIELD node, score
WHERE $as_of IS NULL OR node.created IS NULL OR node.created <= date($as_of)
RETURN node.id AS id, 'PEP' AS label, 'Title' AS heading, node.title AS text, score AS ft,
       node.id AS pep_id, node.title AS title, node.number AS number, node.source_url AS url, node.pagerank AS pagerank
LIMIT $k
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Filter
            Node By Fulltext Index Scan
```
</details>

## Agent tools (each returns rows of src/rel/dst "triples")

### `PEP_NODE`

```cypher
MATCH (p:PEP {id: $id}) RETURN properties(p) AS p
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Node By Index Scan | (p:PEP)
```
</details>

### `INTO_PEP`

Who/what points at the PEP: decisions, authors, delegates, implementing PRs, events.

```cypher
MATCH (a)-[r:DECIDES|AUTHORED|DELEGATE_FOR|IMPLEMENTS|AFFECTS]->(b:PEP {id: $id})
WHERE NOT a:Event OR coalesce(a.applied, true) = true   // replay events stay hidden until applied

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 100
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Filter
            Conditional Traverse | (b)<-[r:AFFECTS|DECIDES|IMPLEMENTS|DELEGATE_FOR|AUTHORED]-(a)
                Filter
                    Node By Index Scan | (b:PEP)
```
</details>

### `DECISION_PROVENANCE`

Where each decision was recorded and who announced it.

```cypher
MATCH (:PEP {id: $id})<-[:DECIDES]-(a:Decision)-[r:RECORDED_IN|ANNOUNCED_BY]->(b)

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (a)-[r:RECORDED_IN|ANNOUNCED_BY]->(b)
        Conditional Traverse | (_anon_0)<-(a:Decision)
            Filter
                Node By Index Scan | (_anon_0:PEP)
```
</details>

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

<details><summary>Execution plan</summary>

```
Project
    Project
        Distinct
            Project
                Unwind
                    Conditional Variable Length Traverse | (_anon_0)-[_anon_1:SUPERSEDES*1..3]->(_anon_2)
                        Filter
                            Node By Index Scan | (_anon_0:PEP)
```
</details>

### `PEP_THREADS`

```cypher
MATCH (a:PEP {id: $id})-[r:DISCUSSED_IN]->(b:Thread)

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 10
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Conditional Traverse | (a)-[r:DISCUSSED_IN]->(b:Thread)
            Filter
                Node By Index Scan | (a:PEP)
```
</details>

### `RELATED_1`

Neighbourhood over citation/supersede/require links (hop count fixed per query).

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..1]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Project
            Distinct
                Project
                    Unwind
                        PathBuilder
                            Conditional Traverse | (_anon_0)-(_anon_2:PEP)
                                Filter
                                    Node By Index Scan | (_anon_0:PEP)
```
</details>

### `RELATED_2`

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..2]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Project
            Distinct
                Project
                    Unwind
                        Conditional Variable Length Traverse | (_anon_0)-[_anon_1:REFERENCES|REQUIRES|SUPERSEDES*1..2]->(_anon_2)
                            Filter
                                Node By Index Scan | (_anon_0:PEP)
```
</details>

### `RELATED_3`

```cypher
MATCH path = (:PEP {id: $id})-[:REFERENCES|SUPERSEDES|REQUIRES*1..3]-(:PEP)
UNWIND relationships(path) AS r WITH DISTINCT r WITH startNode(r) AS a, r, endNode(r) AS b

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
 LIMIT 200
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Project
            Distinct
                Project
                    Unwind
                        Conditional Variable Length Traverse | (_anon_0)-[_anon_1:REQUIRES|REFERENCES|SUPERSEDES*1..3]->(_anon_2)
                            Filter
                                Node By Index Scan | (_anon_0:PEP)
```
</details>

### `FIND_AREA`

```cypher
MATCH (a:Area)
WHERE toLower(a.name) = toLower($t) OR toLower(a.name) CONTAINS toLower($t)
RETURN a.id AS id, a.name AS name, toLower(a.name) = toLower($t) AS exact
ORDER BY exact DESC, size(a.name) ASC
LIMIT 1
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Filter
                Node By Label Scan | (a:Area)
```
</details>

### `AREA_EXPERTS`

Declared (Experts Index) and revealed (commits) owners of one area.

```cypher
MATCH (a:Person)-[r:EXPERT_IN|COMMITTED_TO]->(b:Area {id: $id})

RETURN a.id AS s, labels(a)[0] AS sl, properties(a) AS sp, type(r) AS t, properties(r) AS rp,
       b.id AS d, labels(b)[0] AS dl, properties(b) AS dp
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (b)<-[r:COMMITTED_TO|EXPERT_IN]-(a:Person)
        Filter
            Node By Index Scan | (b:Area)
```
</details>

## Agent memory (one graph per agent)

### `CREATE_ANSWER`

```cypher
CREATE (a:Answer {id: $id, question: $question, text: $text, created_at: $now, as_of: $as_of, stale: false})
```

<details><summary>Execution plan</summary>

```
Commit
    Create | (a:Answer), 
```
</details>

### `LINK_EVIDENCE`

```cypher
MATCH (x {id: $src})
UNWIND $refs AS ref
MERGE (e:Evidence {ref: ref})
ON CREATE SET e.id = 'ev:' + ref, e.ref_label = split(ref, ':')[0]
MERGE (x)-[:DERIVED_FROM]->(e)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (x)-[_anon_0:DERIVED_FROM]->(e), 
        Merge | (e:Evidence), 
            Unwind
                Filter
                    All Node Scan | (x)
            Filter
                Include Pending | (e:Evidence)
                    Node By Label Scan | (e:Evidence)
                        Argument
        Expand Into | (x)->(e:Evidence)
            Argument
```
</details>

### `CREATE_BELIEFS`

```cypher
MATCH (a:Answer {id: $answer_id})
UNWIND $beliefs AS b
CREATE (bl:Belief {id: b.id, text: b.text, status: b.status, confidence: b.confidence, created_at: $now, stale: false})
MERGE (a)-[:DERIVED_FROM]->(bl)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (a)-[_anon_0:DERIVED_FROM]->(bl), 
        Create | (bl:Belief), 
            Unwind
                Filter
                    Node By Label Scan | (a:Answer)
        Filter
            Expand Into | (a)->(bl:Belief)
                Argument
```
</details>

### `LIST_BELIEFS`

```cypher
MATCH (b:Belief)
WHERE $status IS NULL OR b.status = $status
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence,
       b.stale AS stale, b.stale_because AS stale_because, b.created_at AS created_at
ORDER BY b.created_at
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Filter
            Node By Label Scan | (b:Belief)
```
</details>

### `CREATE_ACTION`

```cypher
CREATE (x:Action {id: $id, kind: $kind, payload_json: $payload, status: 'pending', created_at: $now})
WITH x
UNWIND $derived_from AS ref
MATCH (y) WHERE (y:Answer OR y:Belief) AND y.id = ref
MERGE (x)-[:DERIVED_FROM]->(y)
```

<details><summary>Execution plan</summary>

```
Commit
    Merge | (x)-[_anon_0:DERIVED_FROM]->(y), 
        Filter
            All Node Scan | (y)
                Unwind
                    Project
                        Commit
                            Create | (x:Action), 
        Filter
            Expand Into | (x)->(y)
                Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Commit
    Merge | (e)-[_anon_0:SUGGESTS]->(i), 
        Update
            Merge | (i:Interest), 
                Unwind
                    Project
                        Commit
                            Create | (e:Episode), 
                Filter
                    Include Pending | (i:Interest)
                        Node By Label Scan | (i:Interest)
                            Argument
        Filter
            Expand Into | (e)->(i:Interest)
                Argument
```
</details>

### `EXPLAIN_INTEREST`

```cypher
MATCH (e:Episode)-[r:SUGGESTS]->(i:Interest {area_ref: $area})
RETURN e.id AS eid, e.question AS q, e.at AS at, i.area_ref AS area, i.weight AS w
ORDER BY e.at
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Conditional Traverse | (i)<-[r:SUGGESTS]-(e:Episode)
            Filter
                Node By Label Scan | (i:Interest)
```
</details>

### `FORGET_DECREMENT`

```cypher
MATCH (:Episode {id: $id})-[:SUGGESTS]->(i:Interest) SET i.weight = i.weight - 1
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Conditional Traverse | (_anon_0)->(i:Interest)
            Filter
                Node By Label Scan | (_anon_0:Episode)
```
</details>

### `FORGET_EPISODE`

```cypher
MATCH (e:Episode {id: $id}) DELETE e
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Filter
            Node By Label Scan | (e:Episode)
```
</details>

### `DROP_EMPTY_INTERESTS`

```cypher
MATCH (i:Interest) WHERE i.weight <= 0 DELETE i
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Filter
            Node By Label Scan | (i:Interest)
```
</details>

### `LIST_INTERESTS`

```cypher
MATCH (i:Interest) RETURN i.area_ref AS area, i.weight AS weight, i.last_at AS last_at ORDER BY weight DESC
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Node By Label Scan | (i:Interest)
```
</details>

### `AREAS_OF_PEPS`

Areas touched by a set of cited PEPs (for per-user interest memory).

```cypher
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN DISTINCT a.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Conditional Traverse | (p)->(a:Area)
            Filter
                Node By Index Scan | (p:PEP)
```
</details>

## Steward: staleness ripple

### `SUPERSEDERS`

```cypher
MATCH (s:PEP)-[:SUPERSEDES]->(c:PEP)
WHERE c.id IN $changed
RETURN DISTINCT s.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Conditional Traverse | (c)<-(s:PEP)
            Filter
                Node By Index Scan | (c:PEP)
```
</details>

### `RIPPLE_SOFT_1`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..1]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Filter
            Conditional Traverse | (x)->(c:PEP)
                Filter
                    Node By Label Scan | (x:PEP)
```
</details>

### `RIPPLE_SOFT_2`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..2]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Filter
            Conditional Variable Length Traverse | (x)-[_anon_0:REFERENCES|REQUIRES*1..2]->(c)
                Filter
                    Node By Label Scan | (x:PEP)
```
</details>

### `RIPPLE_SOFT_3`

```cypher
MATCH (x:PEP)-[:REFERENCES|REQUIRES*1..3]->(c:PEP)
WHERE c.id IN $changed AND NOT x.id IN $changed AND NOT x.id IN $exclude
RETURN DISTINCT x.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Filter
            Conditional Variable Length Traverse | (x)-[_anon_0:REFERENCES|REQUIRES*1..3]->(c)
                Filter
                    Node By Label Scan | (x:PEP)
```
</details>

### `MARK_PEPS_STALE`

```cypher
MATCH (p:PEP) WHERE p.id IN $ids SET p.stale = true, p.stale_because = $reason
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Index Scan | (p:PEP)
```
</details>

### `MARK_CHUNKS_STALE`

```cypher
MATCH (ch:Chunk)-[:PART_OF]->(p:PEP)
WHERE p.id IN $ids
SET ch.stale = true, ch.stale_because = $reason
RETURN ch.id AS id
```

<details><summary>Execution plan</summary>

```
Project
    Commit
        Update
            Conditional Traverse | (p)<-(ch:Chunk)
                Filter
                    Node By Index Scan | (p:PEP)
```
</details>

### `RIPPLE_EDGES`

```cypher
MATCH (a:PEP)-[r:REFERENCES|REQUIRES|SUPERSEDES]->(b:PEP)
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS s, 'PEP' AS sl, {number: a.number, title: a.title, stale: a.stale} AS sp, type(r) AS t, {} AS rp,
       b.id AS d, 'PEP' AS dl, {number: b.number, title: b.title, stale: b.stale} AS dp
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Conditional Traverse | (a)-[r:SUPERSEDES|REFERENCES|REQUIRES]->(b:PEP)
            Filter
                Node By Index Scan | (a:PEP)
```
</details>

### `CLEAR_STALE`

```cypher
MATCH (n) WHERE n.stale = true SET n.stale = false, n.stale_because = null
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            All Node Scan | (n)
```
</details>

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

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Filter
            Conditional Variable Length Traverse | (x)-[_anon_0:DERIVED_FROM*1..5]->(e)
                Project
                    Commit
                        Update
                            Filter
                                Node By Label Scan | (e:Evidence)
```
</details>

### `MARK_BELIEFS_STALE`

```cypher
MATCH (b:Belief) WHERE b.id IN $ids SET b.status = 'stale', b.stale = true, b.stale_because = $reason
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Label Scan | (b:Belief)
```
</details>

### `MARK_ANSWERS_STALE`

```cypher
MATCH (a:Answer) WHERE a.id IN $ids SET a.stale = true, a.stale_because = $reason
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Label Scan | (a:Answer)
```
</details>

### `BLOCK_ACTIONS`

```cypher
MATCH (x:Action) WHERE x.id IN $ids AND x.status = 'pending' SET x.status = 'blocked', x.reason = $reason RETURN x.id AS id
```

<details><summary>Execution plan</summary>

```
Project
    Commit
        Update
            Filter
                Node By Label Scan | (x:Action)
```
</details>

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

<details><summary>Execution plan</summary>

```
Limit
    Project
        Filter
            Conditional Variable Length Traverse | (a)-[_anon_0:DERIVED_FROM*1..5]->(x)
                Filter
                    Node By Label Scan | (a:Action)
```
</details>

### `ACTION_NODE`

```cypher
MATCH (x:Action {id: $id}) RETURN x.status AS status, x.kind AS kind, x.payload_json AS payload
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Node By Label Scan | (x:Action)
```
</details>

### `EXECUTE_ACTION`

```cypher
MATCH (x:Action {id: $id})
SET x.status = 'done', x.done_at = $now
CREATE (o:Outbox {id: $oid, action_id: $id, kind: x.kind, payload_json: x.payload_json, at: $now})
RETURN o.id AS id
```

<details><summary>Execution plan</summary>

```
Project
    Commit
        Create | (o:Outbox), 
            Update
                Filter
                    Node By Label Scan | (x:Action)
```
</details>

### `SET_ACTION_BLOCKED`

```cypher
MATCH (x:Action {id: $id}) SET x.status = 'blocked', x.reason = $reason
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Filter
            Node By Label Scan | (x:Action)
```
</details>

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

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Filter
                Conditional Variable Length Traverse | (a)-[_anon_0:DERIVED_FROM*1..5]->(e)
                    Filter
                        Node By Label Scan | (a:Action)
```
</details>

## Shared coordination board (lineage:shared)

### `UPSERT_FIX_TASKS`

```cypher
UNWIND $rows AS r
MERGE (t:FixTask {id: r.id})
ON CREATE SET t.status = 'open', t.created_at = $now, t.kind = r.kind, t.target_ref = r.target_ref,
              t.reason = r.reason, t.suggested = r.suggested
RETURN t.id AS id
```

<details><summary>Execution plan</summary>

```
Project
    Commit
        Merge | (t:FixTask), 
            Unwind
            Filter
                Include Pending | (t:FixTask)
                    Node By Label Scan | (t:FixTask)
                        Argument
```
</details>

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

<details><summary>Execution plan</summary>

```
Project
    Commit
        Update
            Merge | (a)-[c:CLAIMED]->(t), 
                Merge | (a:Agent), 
                    Update
                        Limit
                            Sort
                                Project
                                    Filter
                                        Node By Label Scan | (t:FixTask)
                    Filter
                        Include Pending | (a:Agent)
                            Node By Label Scan | (a:Agent)
                                Argument
                Expand Into | (a)-[c:CLAIMED]->(t:FixTask)
                    Argument
```
</details>

### `COMPLETE_TASK`

```cypher
MATCH (t:FixTask {id: $id})
WHERE t.claimed_by = $agent AND t.status = 'claimed'
SET t.status = 'done', t.done_at = $now
RETURN t.id AS id
```

<details><summary>Execution plan</summary>

```
Project
    Commit
        Update
            Filter
                Node By Label Scan | (t:FixTask)
```
</details>

### `LIST_TASKS`

```cypher
MATCH (t:FixTask)
WHERE $status IS NULL OR t.status = $status
RETURN t.id AS id, t.kind AS kind, t.target_ref AS target_ref, t.reason AS reason, t.status AS status,
       t.claimed_by AS claimed_by, t.suggested AS suggested, t.created_at AS created_at
ORDER BY t.created_at, t.id
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Filter
            Node By Label Scan | (t:FixTask)
```
</details>

### `AREA_OWNERS_OF_PEPS`

Who should review a PEP: active listed experts of the areas it concerns.

```cypher
MATCH (p:PEP)-[:CONCERNS]->(:Area)<-[e:EXPERT_IN]-(x:Person)
WHERE p.id IN $ids AND (e.inactive IS NULL OR e.inactive = false)
RETURN p.id AS pep, p.title AS title, collect(DISTINCT coalesce(x.github, x.name)) AS owners
```

<details><summary>Execution plan</summary>

```
Aggregate
    Filter
        Conditional Traverse | (_anon_1)<-[e:EXPERT_IN]-(x:Person)
            Conditional Traverse | (p)->(_anon_1:Area)
                Filter
                    Node By Index Scan | (p:PEP)
```
</details>

## Ownership drift: declared (Experts Index) vs revealed (commits)

### `TRACKED_AREAS`

```cypher
MATCH (:Person)-[:COMMITTED_TO]->(a:Area) RETURN DISTINCT a.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Conditional Traverse | (a)<-(_anon_0:Person)
            Node By Label Scan | (a:Area)
```
</details>

### `DRIFT_DECLARED`

```cypher
MATCH (p:Person)-[e:EXPERT_IN]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, coalesce(e.inactive, false) AS inactive
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (a)<-[e:EXPERT_IN]-(p:Person)
        Filter
            Node By Index Scan | (a:Area)
```
</details>

### `DRIFT_REVEALED`

```cypher
MATCH (p:Person)-[c:COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas
RETURN a.id AS area_id, a.name AS area, coalesce(p.github, p.id) AS who, c.count AS commits, c.last_at AS last_at
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (a)<-[c:COMMITTED_TO]-(p:Person)
        Filter
            Node By Index Scan | (a:Area)
```
</details>

### `AREA_NAMES`

```cypher
MATCH (a:Area) WHERE a.id IN $areas RETURN a.id AS id, a.name AS name
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Node By Index Scan | (a:Area)
```
</details>

## What-if (runs on a GRAPH.COPY fork)

### `PERSON_EXISTS`

```cypher
MATCH (p:Person {id: $id}) RETURN p.id AS id, coalesce(p.name, p.github) AS name
```

<details><summary>Execution plan</summary>

```
Project
    Filter
        Node By Index Scan | (p:Person)
```
</details>

### `COLLAB_COMPONENTS`

Collaboration clusters (size >= 2) via weakly connected components.

```cypher
CALL algo.WCC({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATED']}) YIELD node, componentId
WITH componentId, count(node) AS size
WHERE size >= 2
RETURN count(componentId) AS n
```

<details><summary>Execution plan</summary>

```
Aggregate
    Filter
        Aggregate
            ProcedureCall
```
</details>

### `ACTIVE_IN_AREAS`

Areas where someone is "active": listed and not inactive, or >= 3 commits.

```cypher
MATCH (p:Person)-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
WHERE a.id IN $areas AND ((type(r) = 'EXPERT_IN' AND coalesce(r.inactive, false) = false)
                          OR (type(r) = 'COMMITTED_TO' AND r.count >= 3))
RETURN a.id AS id, a.name AS name, count(DISTINCT p) AS n
```

<details><summary>Execution plan</summary>

```
Aggregate
    Filter
        Conditional Traverse | (a)<-[r:EXPERT_IN|COMMITTED_TO]-(p:Person)
            Filter
                Node By Index Scan | (a:Area)
```
</details>

### `AREAS_OF_PERSON`

```cypher
MATCH (:Person {id: $id})-[r:EXPERT_IN|COMMITTED_TO]->(a:Area)
RETURN DISTINCT a.id AS id
```

<details><summary>Execution plan</summary>

```
Distinct
    Project
        Conditional Traverse | (_anon_0)-[r:COMMITTED_TO|EXPERT_IN]->(a:Area)
            Filter
                Node By Index Scan | (_anon_0:Person)
```
</details>

### `DELETE_PERSON`

```cypher
MATCH (p:Person {id: $id}) DELETE p
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Filter
            Node By Index Scan | (p:Person)
```
</details>

### `TOP_COLLABORATORS`

```cypher
MATCH (:Person {id: $id})-[c:COLLABORATED]-(y:Person)
RETURN coalesce(y.github, y.name, y.id) AS who, c.weight AS w
ORDER BY w DESC LIMIT 5
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Conditional Traverse | (_anon_0)-[c:COLLABORATED]-(y:Person)
                Filter
                    Node By Index Scan | (_anon_0:Person)
```
</details>

### `AREA_COMMITTERS`

```cypher
MATCH (y:Person)-[c:COMMITTED_TO]->(a:Area {id: $area})
WHERE y.id <> $id
RETURN coalesce(y.github, y.name, y.id) AS who, c.count AS n
ORDER BY n DESC LIMIT 3
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Filter
                Conditional Traverse | (a)<-[c:COMMITTED_TO]-(y:Person)
                    Filter
                        Node By Index Scan | (a:Area)
```
</details>

### `PERSON_FOOTPRINT`

```cypher
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
WITH p, count(DISTINCT pep) AS authored
OPTIONAL MATCH (d:Decision)-[:ANNOUNCED_BY]->(p)
RETURN authored, count(DISTINCT d) AS announced
```

<details><summary>Execution plan</summary>

```
Aggregate
    Apply
        Aggregate
            Optional Conditional Traverse | (pep)<-(p:Person)
                Filter
                    Node By Index Scan | (p:Person)
        Optional
            Conditional Traverse | (d)->(p:Person)
                Argument
```
</details>

## API listings

### `LIST_EVENTS`

```cypher
MATCH (e:Event)-[:AFFECTS]->(p:PEP)
RETURN e.id AS id, e.kind AS kind, e.summary AS summary, toString(e.at) AS at, e.applied AS applied,
       e.source_url AS source_url, p.id AS pep, e.payload_json AS payload
ORDER BY at
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Conditional Traverse | (e)->(p:PEP)
            Node By Label Scan | (e:Event)
```
</details>

### `LIST_ACTIONS`

```cypher
MATCH (x:Action)
RETURN x.id AS id, x.kind AS kind, x.status AS status, x.reason AS reason, x.payload_json AS payload, x.created_at AS created_at
ORDER BY x.created_at
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        Node By Label Scan | (x:Action)
```
</details>

### `SEARCH_PEOPLE`

```cypher
MATCH (p:Person)
WHERE toLower(coalesce(p.name, '')) CONTAINS toLower($q) OR toLower(coalesce(p.github, '')) CONTAINS toLower($q)
OPTIONAL MATCH (p)-[:AUTHORED]->(pep:PEP)
RETURN p.id AS id, p.name AS name, p.github AS github, count(pep) AS peps
ORDER BY peps DESC, id LIMIT 15
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Aggregate
            Optional Conditional Traverse | (pep)<-(p:Person)
                Filter
                    Node By Label Scan | (p:Person)
```
</details>

## Index card for one node

### `CARD_BY_LABEL`

```cypher
MATCH (n:PEP {id: $id})
OPTIONAL MATCH (n)-[r]-(m)
WITH n, r, m LIMIT 60
RETURN properties(n) AS props, type(r) AS rel, startNode(r).id = n.id AS outgoing, m.id AS mid, labels(m)[0] AS ml,
       coalesce(m.title, m.name, m.github, m.kind, m.heading) AS mname
```

<details><summary>Execution plan</summary>

```
Project
    Limit
        Project
            Optional Conditional Traverse | (n)-[r]-(m)
                Filter
                    Node By Index Scan | (n:PEP)
```
</details>

### `BELIEFS_ON_REF`

```cypher
MATCH (b:Belief)-[:DERIVED_FROM]->(:Evidence {ref: $ref})
RETURN b.id AS id, b.text AS text, b.status AS status, b.confidence AS confidence
```

<details><summary>Execution plan</summary>

```
Project
    Conditional Traverse | (_anon_1)<-(b:Belief)
        Filter
            Node By Label Scan | (_anon_1:Evidence)
```
</details>

### `DELETE_CONCERNS`

```cypher
MATCH (:PEP)-[r:CONCERNS]->(:Area) DELETE r
```

<details><summary>Execution plan</summary>

```
Commit
    Delete
        Conditional Traverse | (_anon_1)<-[r:CONCERNS]-(_anon_0:PEP)
            Node By Label Scan | (_anon_1:Area)
```
</details>

### `AREAS_NAMED_IN`

Graph-only backend: which known module names appear in a question.

```cypher
MATCH (a:Area)
WHERE size(a.name) >= 4 AND toLower($q) CONTAINS toLower(a.name)
RETURN a.name AS name
ORDER BY size(a.name) DESC
LIMIT 1
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Filter
                Node By Label Scan | (a:Area)
```
</details>

## Algorithms as agent tools

### `RESOLVE_PERSON`

```cypher
MATCH (p:Person)
WHERE toLower(p.name) = toLower($q) OR toLower(p.github) = toLower($q)
   OR toLower(p.name) CONTAINS toLower($q)
RETURN p.id AS id, (toLower(coalesce(p.name, '')) = toLower($q) OR toLower(coalesce(p.github, '')) = toLower($q)) AS exact
ORDER BY exact DESC LIMIT 1
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Project
            Filter
                Node By Label Scan | (p:Person)
```
</details>

### `RESOLVE_AREA`

```cypher
MATCH (a:Area) WHERE toLower(a.name) = toLower($q) RETURN a.id AS id LIMIT 1
```

<details><summary>Execution plan</summary>

```
Limit
    Project
        Filter
            Node By Label Scan | (a:Area)
```
</details>

### `BETWEENNESS_PEOPLE`

Who bridges otherwise separate groups of collaborators. Runs on TIE (two-way copies of COLLABORATED): FalkorDB's betweenness follows edge direction, and collaboration has none.

```cypher
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['TIE']}) YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC
```

<details><summary>Execution plan</summary>

```
Sort
    Project
        ProcedureCall
```
</details>

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

<details><summary>Execution plan</summary>

```
Sort
    Project
        Filter
            Aggregate
                ProcedureCall
```
</details>

### `AREA_COUNTS_FOR_PEPS`

```cypher
MATCH (p:PEP)-[:CONCERNS]->(a:Area)
WHERE p.id IN $ids
RETURN a.name AS area, count(p) AS n
ORDER BY n DESC LIMIT 4
```

<details><summary>Execution plan</summary>

```
Limit
    Sort
        Aggregate
            Conditional Traverse | (p)->(a:Area)
                Filter
                    Node By Index Scan | (p:PEP)
```
</details>

### `MATERIALIZE_TIES`

Two-way TIE edges for direction-sensitive algorithms (betweenness).

```cypher
MATCH (a:Person)-[c:COLLABORATED]->(b:Person)
MERGE (a)-[t1:TIE]->(b) SET t1.weight = c.weight
MERGE (b)-[t2:TIE]->(a) SET t2.weight = c.weight
```

<details><summary>Execution plan</summary>

```
Commit
    Update
        Merge | (b)-[t2:TIE]->(a), 
            Update
                Merge | (a)-[t1:TIE]->(b), 
                    Conditional Traverse | (a)-[c:COLLABORATED]->(b:Person)
                        Node By Label Scan | (a:Person)
                    Expand Into | (a)-[t1:TIE]->(b:Person)
                        Argument
            Expand Into | (b)-[t2:TIE]->(a:Person)
                Argument
```
</details>
