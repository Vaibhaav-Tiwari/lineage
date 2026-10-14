# Lineage: graph model sketch (pre-event notes)

FalkorDB holds **4 kinds of graphs**. Circles are **nodes**; arrows are **edges** (relationships).

| Graph | Who writes it | What's in it |
|---|---|---|
| `lineage:company` | the ingest step (and the Steward, for "stale" flags) | the Python project: people, proposals, decisions, discussions |
| `lineage:agent:<name>` | each agent, its own only | what that agent believes and answered |
| `lineage:user:<id>` | the Historian | what we remember about each user |
| `lineage:shared` | Steward + workers | the to-do board for fixing stale things |

---

## 1. Company graph: the "company brain"

### Nodes

| Node | Example | Comes from |
|---|---|---|
| **Person** | Larry Hastings (`person:larryhastings`) | PEP authors, forum posters, Experts Index, GitHub |
| **Team** | Steering Council | governance PEPs |
| **Area** | `asyncio`, `typing` | Experts Index |
| **PEP** | PEP 649, status Final | peps.json |
| **Decision** | "PEP 649 accepted, 2023-05-08" | PEP status + resolution link |
| **Thread** | forum topic about PEP 649 | discuss.python.org |
| **Post** | the post announcing acceptance | discuss.python.org |
| **PR** | a CPython pull request implementing PEP 649 | GitHub |
| **Chunk** | one section of a PEP's text, with an embedding for search | PEP text |

### Edges

| Edge | Meaning |
|---|---|
| Person **AUTHORED** PEP | wrote the proposal |
| Decision **DECIDES** PEP | accepted / rejected / superseded it |
| Decision **ANNOUNCED_BY** Person | who announced the decision |
| Decision **RECORDED_IN** Post | where the decision was written down |
| PEP **DISCUSSED_IN** Thread | where it was debated |
| Person **POSTED** Post, Post **IN** Thread | who said what, where |
| PEP **SUPERSEDES** PEP | new idea replaced old idea ⭐ *drives the demo* |
| PEP **REFERENCES** / **REQUIRES** PEP | one proposal relies on another ⭐ *drives the ripple* |
| PR **IMPLEMENTS** PEP | the code that made it real |
| PEP **CONCERNS** Area | which part of Python it affects |
| Person **EXPERT_IN** Area | **listed** owner (declared) |
| Person **COMMITTED_TO** Area | **actual** contributor (revealed, last 12 months) |
| Person **MEMBER_OF** Team | governance roles |
| Chunk **PART_OF** PEP | text pieces for search |

### Example path (what an answer "walks")

```
(Larry Hastings)-[:AUTHORED]->(PEP 649)-[:SUPERSEDES]->(PEP 563)
(Decision: accept 649)-[:DECIDES]->(PEP 649)
(Decision)-[:RECORDED_IN]->(Post #1)-[:IN]->(Thread "PEP 649…")
```

---

## 2. Agent memory graph: one per agent

| Node | Meaning |
|---|---|
| **Evidence** `{ref: "pep:563"}` | a pointer to a company-graph node (same id) |
| **Belief** | something the agent concluded. Status is tentative, committed, or stale |
| **Answer** | what it told a user |
| **Action** | something it wants to do, e.g. "add to FAQ". Status is pending, blocked, or done |

Chain: **Action → Answer → Belief → Evidence**, all linked by **DERIVED_FROM** edges.

**Why Evidence is a pointer:** a query can't jump between two graphs, so the agent's graph stores the company node's **id**. When PEP 563 changes, we look up `ref = "pep:563"` in every agent's graph. Then we follow DERIVED_FROM backwards and mark everything built on it as stale.

---

## 3. User memory graph: one per user

- **Episode** = a question the user asked.
- **Interest** = an area they care about, e.g. typing, with a weight.
- Episode **SUGGESTS** Interest. This answers "why do you think I care about typing?" and lets the user delete an episode, which makes the system forget it.

## 4. Shared board

- **FixTask** = "PEP X cites a replaced PEP, so someone should update it".
- Agent **CLAIMED** FixTask: one worker per task, guaranteed. FalkorDB runs writes to one graph one at a time, so two agents can't grab the same task.

## 5. Temporary "what-if" copy

- `lineage:fork:<id>` is made with `GRAPH.COPY` of the company graph.
- Delete a person in the copy only, re-run the graph algorithms, then compare the results with the original.
- Delete the copy afterwards.
