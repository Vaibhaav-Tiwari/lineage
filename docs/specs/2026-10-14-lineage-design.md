# Lineage: Design Spec

> A company brain that **un-learns**. It answers *why, who, since when*, and *what breaks if they leave*. Its agents retract what they believed when the company changes.
>
> **Hackathon:** Graph Hacks, Context for AI Agents (WeMakeDevs × FalkorDB), Oct 15 00:01 IST to Oct 18 23:59 IST, 2026.
> **Tracks entered:** Track 02 (Agent Memory & Coordination) and Track 03 (Company Brain).
> **Status:** pre-event design notes. Per the rules, ideas, notes, graph-model sketches and diagrams may be prepared before the start, and **all code is written after 00:01 IST Oct 15**.

---

## 1. Problem and pitch

Company knowledge tools answer *what* from text chunks. They fail on three things:

1. **Why.** Decisions are not first-class. You get a paragraph, not the chain: proposal → discussion → who decided → what implemented it → what superseded it.
2. **Freshness.** Staleness is timer-based (Guru) or absent. When a decision is superseded, nothing tells the docs, the cached answers, or *the AI agents that already absorbed the old truth*.
3. **People risk.** Who actually knows this area, versus who is listed? What breaks if they leave?

Agent memory tools (Mem0, Graphiti, Letta, Supermemory, Hermes) also don't track **which belief came from which evidence**. They cannot cascade a retraction, and they don't isolate agents' memories at the database level.

**Lineage** puts the company, every agent's beliefs, and every answer into FalkorDB graphs connected by `DERIVED_FROM` lineage. One mechanism serves both tracks: **change propagates along lineage**.

Pitch line: *"Glean tells you what. Lineage tells you why, who, since when, and what breaks if they leave, and its agents un-learn when the company changes."*

---

## 2. The demo "company": the Python project (public data)

| Need | Source | Access |
|---|---|---|
| Docs + decisions | `https://peps.python.org/api/peps.json` (status, `superseded_by`, `replaces`, `requires`, `resolution`, `discussions_to`, authors, created) | anonymous JSON |
| Doc text | `python/peps` repo, `peps/pep-NNNN.rst` (headers: PEP-Delegate, Discussions-To, Post-History, Resolution) | raw GitHub |
| Chat / discussion | `discuss.python.org/t/<slug>/<id>.json` (posts: username, created_at, cooked, post_number, reply_to_post_number; 20 posts per page, `post_stream.stream` lists all ids) | anonymous JSON, polite rate |
| Declared ownership | `python/devguide` `core-team/experts.rst`: Module → GitHub handles, `*` = may be assigned issues, `(inactive)` marker | raw GitHub |
| Revealed ownership + implementation | `python/cpython` GitHub API: commits by path (Lib/<module>), PRs mentioning "PEP NNN" | GitHub token (5000 req/h) |
| Teams | Steering Council terms (PEP 13 + election PEPs 8100-series), Typing Council (PEP 729) | parsed from PEP text, hand-checked |

**Corpus scope** (keeps ingestion under about 30 min):
- **Metadata:** all PEPs.
- **Text, threads and PRs:** a *focus set* of about 120–150 PEPs. That is typing, packaging, governance/process, plus every PEP in a supersede or replace chain.
- **Ownership drift:** about 15 stdlib modules over the last 12 months.

**Hero storyline (confirm on prep day):** annotation evaluation. PEP 563 (`from __future__ import annotations`) was later marked Superseded by PEP 649/749 (deferred evaluation, Python 3.14). It is a real, relatable "the truth changed" event. The backup chain is PEP 5 → 387 or PEP 241 → 314 → 345.

**Stretch:** Rust adapter (team API JSON + rfcbot FCP comments) behind the same canonical schema.

**Privacy rules:**
- Use public handles only.
- Show ownership and departure metrics **per area**, never as a ranking of people.
- Label any synthetic overlay `synthetic: true` in the graph and the UI.

---

## 3. Architecture

```mermaid
flowchart LR
  subgraph Sources[Public sources]
    P[peps.json + PEP rst]
    D[discuss.python.org JSON]
    E[devguide experts.rst]
    G[CPython GitHub API]
  end
  Sources --> ING[Ingest pipeline\n(cache raw → parse → identity resolve → embed → UNWIND MERGE)]
  ING --> C[(lineage:company)]
  subgraph FalkorDB[FalkorDB instance — one graph per concern]
    C
    AH[(lineage:agent:historian)]
    AS[(lineage:agent:steward)]
    U[(lineage:user:&lt;id&gt;)]
    SH[(lineage:shared — tasks/claims)]
    F[(lineage:fork:&lt;id&gt; — GRAPH.COPY)]
  end
  HIST[Historian agent\nClaude + graph tools] -->|read| C
  HIST -->|write beliefs/answers| AH
  HIST -->|episodic memory| U
  STW[Steward agent] -->|read/write staleness| C
  STW -->|fan-out stale refs| AH
  STW -->|create FixTasks| SH
  WI[What-if service] -->|GRAPH.COPY + algorithms| F
  API[FastAPI] --> HIST & STW & WI
  MCP[MCP server] --> HIST
  WEB[Next.js UI\nAsk · Ripple · Org · Memory · Ops] --> API
```

**Key design decisions** (each one is something to explain to judges):

1. **One graph per concern, isolation enforced by the database.**
   - The company graph is shared and each agent and user has its own graph. Each agent connects as its own Redis ACL user.
   - The Historian gets full access to `lineage:agent:historian` and **read-only** access to `lineage:company`.
   - Writes to different graphs don't queue behind each other, because FalkorDB serializes writes *per graph*.
2. **Lineage across graphs.**
   - Cypher cannot cross graphs. So an agent graph holds `(:Evidence {ref})` stub nodes that mirror the stable ids of company nodes.
   - A staleness event computes stale ids in the company graph, then fans out by id to each agent graph. Inside the agent graph it walks `DERIVED_FROM*` back from the stubs.
3. **Counterfactuals with `GRAPH.COPY`.**
   - FalkorDB's algorithm procedures (betweenness, WCC, label propagation) run over whole label/relationship sets and can't exclude a node.
   - So "what if X leaves" copies the company graph to a fork, deletes X there, and re-runs the algorithms. The live graph is never touched.
4. **Deterministic first, LLM last.**
   - Structured sources are parsed deterministically, which gives exact provenance.
   - The LLM is used only for answer synthesis, claim extraction from answers, and (stretch) decision detection in threads.
5. **Answers are evidence subgraphs.**
   - Every cited id is checked to exist in the evidence the tools returned.
   - The UI renders the connecting subgraph, not footnotes.
   - If no evidence path exists, the agent abstains.

**Stack:**
- **Backend:** Python 3.12 with `uv`, `falkordb` (async client), FastAPI, `anthropic` SDK (model `claude-sonnet-5-5`, configurable), `fastembed` (`BAAI/bge-small-en-v1.5`, 384-d, local, no key), `httpx`, `docutils` for rst, `mcp` (FastMCP), pytest.
- **Frontend:** Next.js + Cytoscape.js.
- **Runtime:** FalkorDB pinned image tag via docker compose.
- **Deploy:** FalkorDB + API on Railway (Docker, persistent volume). Web on Vercel.

---

## 4. Graph model

### 4.1 `lineage:company`

**Nodes.** Every node has a `id` (stable string), `source_url`, and `synthetic` (bool).

| Label | Key properties |
|---|---|
| `Person` | `id` = `person:<github or slug>`, `name`, `github`, `discourse`, `aliases[]` |
| `Team` | `id` = `team:<slug>`, `name` (Steering Council, Typing Council) |
| `Area` | `id` = `area:<name>`, `name`, `kind` (module/interest/tool) |
| `PEP` | `id` = `pep:<n>`, `number`, `title`, `status`, `type`, `topic`, `created` (date), `python_version`, `pagerank` (float), `stale` (bool), `stale_because` (string) |
| `Chunk` | `id` = `chunk:pep:<n>:<i>`, `heading`, `text`, `emb` (vecf32 384) |
| `Decision` | `id` = `decision:pep:<n>:<kind>`, `kind` (accept/reject/supersede/withdraw/defer), `at` (date or null), `summary` |
| `Thread` | `id` = `thread:<topic_id>`, `title`, `created_at`, `posts_count` |
| `Post` | `id` = `post:<post_id>`, `post_number`, `created_at`, `text`, `emb` |
| `PR` | `id` = `pr:<n>`, `title`, `merged_at` |
| `Event` | `id` = `event:<slug>`, `kind`, `at`, `payload_json`. A replayable change event; the demo timeline. |
| `FixTask` | Not stored here; lives in `lineage:shared`. |

**Relationships:**

```
(Person)-[:AUTHORED]->(PEP)
(Person)-[:DELEGATE_FOR]->(PEP)
(PEP)-[:SUPERSEDES]->(PEP)            (from superseded_by / replaces)
(PEP)-[:REQUIRES]->(PEP)
(PEP)-[:REFERENCES {count}]->(PEP)    (from "PEP NNN" mentions in text)
(Chunk)-[:PART_OF]->(PEP)
(Decision)-[:DECIDES]->(PEP)
(Decision)-[:RECORDED_IN]->(Post|Thread)
(Decision)-[:ANNOUNCED_BY]->(Person)  (author of the resolution post)
(PEP)-[:DISCUSSED_IN]->(Thread)
(Person)-[:POSTED]->(Post)-[:IN]->(Thread)
(PR)-[:IMPLEMENTS]->(PEP)
(Person)-[:AUTHORED_PR]->(PR)
(PEP)-[:CONCERNS]->(Area)
(Person)-[:EXPERT_IN {assignable, inactive}]->(Area)        declared
(Person)-[:COMMITTED_TO {count, last_at}]->(Area)           revealed (last 12 months)
(Person)-[:MEMBER_OF {role, since, until}]->(Team)
(Person)-[:COLLABORATED {weight}]->(Person)                 derived: co-author, co-thread, co-area
(Event)-[:AFFECTS]->(PEP)
```

**Indexes and constraints:**
- Range indexes on `id` for every label, with a UNIQUE constraint on `id`.
- Vector indexes on `Chunk.emb` and `Post.emb` (cosine, dim 384).
- Full-text indexes on `PEP.title`, `Chunk.text` and `Post.text`.
- Range indexes on `PEP.status` and `Decision.at`.

### 4.2 `lineage:agent:<name>` (one per agent)

```
(:Evidence {id, ref, ref_label})                          ref = stable id in lineage:company
(:Belief {id, text, status, confidence, created_at, stale, stale_because})
     status ∈ tentative | committed | stale | retracted
(:Answer {id, question, text, created_at, as_of, stale})
(:Action {id, kind, payload_json, status, reason})        status ∈ pending | blocked | done
(Belief)-[:DERIVED_FROM]->(Evidence|Belief)
(Answer)-[:DERIVED_FROM]->(Evidence|Belief)
(Action)-[:DERIVED_FROM]->(Answer|Belief)
```

### 4.3 `lineage:user:<uid>` (episodic and semantic memory per user)

```
(:Episode {id, question, answer_id, at})
(:Interest {area_ref, weight, last_at})
(Episode)-[:SUGGESTS]->(Interest)
```

### 4.4 `lineage:shared` (coordination)

```
(:Agent {name})
(:FixTask {id, kind, target_ref, reason, status, created_at})   status ∈ open | claimed | done
(Agent)-[:CLAIMED {until}]->(FixTask)
```

### 4.5 `lineage:fork:<id>`

A `GRAPH.COPY` of `lineage:company`. It is deleted after each what-if query, or by a time-to-live sweep.

---

## 5. Agents and services

| Component | Reads | Writes | Job |
|---|---|---|---|
| **Historian** | company (read-only ACL), its own graph, user graph | its own graph, user graph | Answers *why / who / when / as-of* questions with Claude tool-use over graph tools. Returns an Answer plus an evidence subgraph. Extracts 1–3 Beliefs per answer with `DERIVED_FROM` edges. |
| **Steward** | company, all agent graphs | company (`stale` flags), agent graphs (stale fan-out), shared | Applies change Events. Ripples staleness through `SUPERSEDES` / `REFERENCES` / `PART_OF`. Fans out to agent graphs. Blocks Actions whose lineage touches stale nodes. Opens FixTasks for area owners. |
| **What-if service** | company | fork graphs | Copies the graph, removes a person, recomputes orphaned areas and betweenness / communities, returns the diff, deletes the fork. |
| **Ownership service** | company | – | Declared vs. revealed drift per area. |
| **MCP server** | via Historian tools | – | Exposes `ask`, `decision_path`, `who_knows`, `as_of` to Claude Desktop / Code. |

**Historian tools** (JSON-schema tool definitions; each returns node ids plus a compact payload):

| Tool | Returns |
|---|---|
| `search(query, k)` | Hybrid ranked hits (Chunk/Post/PEP) |
| `decision_path(pep_number)` | Decision chain subgraph |
| `pep_timeline(pep_number)` | Ordered events: created, posts, decision, supersede, PRs |
| `who_knows(area_or_topic)` | Declared + revealed experts with recency |
| `related_peps(pep_number, hops)` | Neighbors over REFERENCES/SUPERSEDES/REQUIRES |
| `as_of(date)` | Sets a temporal filter for subsequent calls |

**Action gate rule:** an Action may execute only if no `DERIVED_FROM*` path from it reaches a Belief, Answer or Evidence that is `stale = true` or has status `tentative`. The gate returns the offending path as its reason.

---

## 6. Algorithms and queries the product depends on

| Capability | FalkorDB feature |
|---|---|
| Hybrid retrieval | `db.idx.vector.queryNodes` (distance, **ascending** = more similar) + `db.idx.fulltext.queryNodes` + traversal expansion, re-ranked with precomputed `pagerank` |
| Influence of PEPs | `algo.pageRank('PEP','REFERENCES')`, stored as `PEP.pagerank` |
| Bridges between people | `algo.betweenness({nodeLabels:['Person'], relationshipTypes:['COLLABORATED']})` |
| Knowledge clusters | `algo.labelPropagation({nodeLabels:['Person'], relationshipTypes:['COLLABORATED']})` |
| Silos | `algo.WCC` on the same projection |
| Decision provenance | Variable-length path PEP ← Decision → Post → Person, plus `SUPERSEDES*` chains |
| Staleness ripple | Bounded variable-length traversal `(:PEP {id:$changed})<-[:SUPERSEDES|REFERENCES|REQUIRES*1..3]-()`, plus Chunks via `PART_OF` |
| Time travel | `date()` comparisons on `created`, `Decision.at`, `MEMBER_OF.since/until` |
| Counterfactual | `GRAPH.COPY`, `DELETE` on the fork, algorithms re-run, `GRAPH.DELETE` |
| Coordination | Atomic single-query claim in `lineage:shared` (writes are serialized per graph) |
| Observability | `GRAPH.LIST`, `GRAPH.MEMORY USAGE`, `GRAPH.SLOWLOG`, `GRAPH.PROFILE` |

All Cypher lives in `lineage/graph/queries.py` as named constants and is generated into `docs/queries.md` for the README requirement.

---

## 7. UI

1. **Ask:**
   - Chat with the Historian.
   - The answer comes with an evidence graph (Cytoscape) and a citation list linking to the original URLs.
   - An "as of" date picker.
   - An "abstained: no path found" state.
2. **Ripple:**
   - Event timeline with an **Apply** button.
   - The graph animates stale nodes red.
   - Side panel lists stale docs, stale beliefs per agent, stale answers, blocked actions (each with its reason path), and opened FixTasks.
3. **Org:**
   - Ownership drift per area ("listed but quiet" / "active but unlisted").
   - Communities view.
   - **What-if:** pick a person, run the fork, and see orphaned areas plus the betweenness shift. A badge shows the fork graph's memory.
4. **Memory:**
   - Per-agent belief list with lifecycle status.
   - Per-user "what do you remember about me / why", shown as an episode → interest path, with a **forget** control.
5. **Ops strip:** `GRAPH.LIST`, memory per graph, slowlog top 3.

---

## 8. Scope tiers

- **MVP (required to submit):**
  - Ingest PEPs, text, experts, and resolution threads.
  - Historian with evidence subgraph and citations.
  - Steward ripple on one replayed Event, with fan-out to the Historian graph.
  - Ask + Ripple pages.
  - README, video, deploy.
- **Core (target):**
  - Revealed ownership from GitHub, plus the drift view.
  - What-if fork.
  - Action gate.
  - Per-user memory.
  - ACL-enforced agent graphs.
  - MCP server.
  - Eval numbers.
- **Stretch:**
  - FixTask claims across two Steward workers.
  - Communities view.
  - Decision detection in threads.
  - Rust adapter.
  - Time-travel slider over Steering Council terms.

**Cut-lines:**
- If Day 2 ends without a working Historian, drop the GitHub data.
- If Day 3 ends without the ripple, drop what-if.

---

## 9. Evaluation

`eval/questions.yaml` holds 20 questions with expected facts and expected source ids. Examples:
- "Who announced the acceptance of PEP 695?"
- "What superseded PEP 563?"
- "Who should I ask about argparse?"
- "What did Python decide about the GIL?"

| Metric | Target |
|---|---|
| Answer correctness (LLM judge + manual spot check) | ≥ 80% |
| Citation validity (cited ids exist and are in the tool evidence) | 100% (enforced) |
| Abstention on 3 out-of-corpus questions | 3/3 |
| Ripple recall on the replayed event (hand-labeled dependent set) | ≥ 90% |
| Latency p50 / p95 per tool, from timings + `GRAPH.PROFILE` | reported |

---

## 10. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Identity resolution across PEP names / GitHub / Discourse | Alias map file + FLEX `jaroWinkler` ≥ 0.92 + manual overrides for the focus set |
| Discourse pagination / rate limits | Fetch only the first page plus the resolution post. Cache raw JSON. 1 req/s |
| GitHub rate limits | Token, limited module set, cached raw |
| LLM latency or cost | Cap tool calls at 6 per answer. Cache answers per question + `as_of` |
| FalkorDB ACL syntax differs in the pinned version | Verified by a test in Task 1. Fallback: per-graph credentials enforced in the app, stated honestly in the README |
| Hero storyline facts wrong | Verified on prep day from peps.json. Backup chains listed in §2 |
