# Data sources and runtime: verified notes (prep day, 2026-10-14)

These are pre-event notes (allowed by the rules). Everything below was checked live today.

## 0. Local runtime (done)

- **Docker Desktop:** 29.7.2 on Apple Silicon (arm64).
- **FalkorDB image:** `falkordb/falkordb:6.0.2`. Native arm64 manifest, Rust engine, released 2026-10-08. **Pin this tag.** Avoid `latest` and `edge`.
- **Container `lineage-falkordb`:**
  - `--restart unless-stopped`.
  - Bound to **127.0.0.1 only**: Redis on 6379, Browser on 3000.
  - Named volume `lineage-falkordb-data` mounted at `/var/lib/falkordb/data` (the image's `FALKORDB_DATA_PATH`).
  - `FALKORDB_ARGS=MAX_QUEUED_QUERIES 25 TIMEOUT_DEFAULT 5000 TIMEOUT_MAX 30000 RESULTSET_SIZE 10000`. The image default was `TIMEOUT 1000`, which is too tight for agent queries.
- **Browser:** http://localhost:3000 (connect to host `localhost`, port `6379`, no password locally).

**Verified working on 6.0.2:**

- Procedures:
  - `algo.BFS`, `algo.HarmonicCentrality`, `algo.MSF`, `algo.SPpaths`, `algo.SSpaths`, `algo.WCC`
  - `algo.betweenness`, `algo.labelPropagation`, `algo.maxFlow`, `algo.pageRank`
  - `db.idx.vector.*`, `db.idx.fulltext.*`, `db.constraints`, `db.indexes`
- **Vector `score` is a distance.** Querying `[1,0,0]` returned `a≈0, b=0.006, c=1`. Sort ascending; similarity = `1 - score`.
- `GRAPH.COPY`: the fork can be modified independently. A deleted node in the fork leaves base = 3 nodes, fork = 2.
- `GRAPH.MEMORY USAGE`, `GRAPH.UDF LOAD` (JavaScript UDF returned 42), and `date()` comparison with `duration()` arithmetic.
- **Not available on 6.0.x:** A\*, CCH and Louvain/Leiden. We don't need them.

### Per-graph ACL (important finding)

- The documented recipe `+@all ~own:* %R~shared:*` **does NOT work** on 6.0.2. Every graph command, including `GRAPH.RO_QUERY`, needs read/write key access, so reads of the shared graph fail with `NOPERM`. Worth reporting on the FalkorDB Discord.
- **Working recipe:** a Redis 7 ACL *selector* that allows only `GRAPH.RO_QUERY` on the shared graph.

  ```
  ACL SETUSER historian on >*** resetkeys -@all ~lineage:agent:historian +@all (~lineage:company +GRAPH.RO_QUERY)
  ```

- **Verified results:**
  - RO read of shared succeeds.
  - `GRAPH.QUERY` (write) on shared fails with `NOPERM`.
  - A write sent through `GRAPH.RO_QUERY` is refused by the engine ("only on read-only queries").
  - Writing its own graph succeeds.
  - Touching any other graph fails with `NOPERM`.
- **Persistence:** `ACL SETUSER` is in-memory only, so the app must (re)create users at startup. Alternatively use an ACL file plus `ACL SAVE`.

## 1. Python project (PRIMARY corpus)

| Source | Verified facts | Access | Licence |
|---|---|---|---|
| `peps.python.org/api/peps.json` | **745 PEPs.** Statuses: Final 375, Rejected 132, Withdrawn 72, Draft 55, Active 38, Deferred 36, Superseded 25, Accepted 11, Provisional 1. **31 PEPs have `superseded_by`.** 60 have a discuss.python.org resolution. | Anonymous, one 430 KB file | PEPs are public domain or CC0-1.0, per each PEP's Copyright section |
| PEP source `python/peps/peps/pep-NNNN.rst` | Header fields include PEP-Delegate, Discussions-To, Post-History, Resolution | raw.githubusercontent.com | as above |
| `discuss.python.org/t/<id>.json` | Anonymous 200 OK. `post_stream.posts` has 20 per page, and `post_stream.stream` lists every post id | Anonymous; be polite, ~1 req/s | Forum content: no explicit licence. Link back and quote briefly; don't republish whole threads |
| `python/devguide` `core-team/experts.rst` | RST simple table Module → GitHub handles. `*` = may be assigned issues. `(inactive)` marks inactive people | raw GitHub | **CC0-1.0** |
| `python/cpython` GitHub API | Commits by path → revealed ownership. PR search for "PEP NNN" | **Token needed.** Unauthenticated: 60 core and 10 search per hour. Authenticated: 5,000 core and 30 search per min | Repo licence reported as NOASSERTION (PSF licence); we store metadata only |

**Parsing gotchas found:**

- The `resolution` field is **not always a bare URL**.
  - PEP 649: ``08-May-2023 <https://discuss.python.org/t/pep-649-deferred-evaluation…>`__`` (RST link with a date).
  - PEP 563: a `mail.python.org` pipermail URL.
  - **The parser must extract the URL and date from RST link syntax and accept mail.python.org.** Add this as a test case in Plan Task 3 and Task 7.
- `superseded_by` can be a list in a string: `"649, 749"`.
- `created` uses the `DD-Mon-YYYY` format.

**Hero storyline: CONFIRMED.**

- **PEP 563** "Postponed Evaluation of Annotations": status **Superseded**, `superseded_by = "649, 749"`, created 2017-09-08. Resolution is a python-dev mail from Dec 2017.
- **PEP 649** "Deferred Evaluation Of Annotations Using Descriptors": **Final**, `replaces = 563`. Resolution 2023-05-08 on discuss.python.org.
- **PEP 749** "Implementing PEP 649": **Final**. Resolution 2025-05-05 on discuss.python.org.
- **Replay event:** 563 goes Accepted → Superseded by 649 + 749 at 2025-05-05.

**Backup chain:** packaging metadata **241 → 314 → 345 → 566**, a 4-step supersede chain. It's great for showing a multi-hop ripple.

## 2. Rust project (STRETCH adapter, or a second "org" for multi-tenant demo)

| Source | Verified facts | Access | Licence |
|---|---|---|---|
| Team API `team-api.infra.rust-lang.org/v1/teams.json` | **172 teams** (78 team, 47 marker_team, 32 working_group, 15 project_group). **674 distinct current members.** | Anonymous, one 416 KB file | **Apache-2.0** (rust-lang/team) |
| `rust-lang/rfcs` repo `text/NNNN-*.md` | **646 merged RFCs.** Header: `Feature Name`, `Start Date`, `RFC PR`, `Rust Issue` or `Tracking Issue`, sometimes `Initiative`. Only merged RFCs are in `text/`; closed and postponed ones exist only as PRs. | git / raw GitHub | **Apache-2.0** |
| RFC PR comments (GitHub API) | rfcbot data. Example below. | Token needed for volume | GitHub ToS; store metadata + links |
| Zulip `rust-lang.zulipchat.com` | Web-public in the browser, **but the API requires authentication**: anonymous `/messages` and `/streams` return "Not logged in". It's Zulip 12, feature level 511. | Would need a Zulip account + API key | No explicit licence |

**Team API fields:**
- Per team: `name`, `kind`, `subteam_of`, `top_level`, `members[{name, github, github_id, is_lead, roles?}]`, `alumni[...]`, `github.teams[{org,name,members}]`, `website_data{…, zulip_stream}`, `roles`.
- **No join or leave dates**, so time travel over membership is impossible from this source.
- `lang` has 5 members (lead `tmandry`), 8 alumni, Zulip stream `t-lang`, and 14 subteams (`lang-advisors`, `opsem`, `spec`, `style`, `wg-async`, …).
- Top-level teams: compiler, devtools, infra, lang, launching-pad, libs, mods.

**rfcbot format** (verified on rust-lang/rfcs#3137 let-else and #3681 default field values):

- **Human commands**, one per line, each with a timestamp:
  - `@rfcbot merge` or `@rfcbot fcp merge`
  - `@rfcbot reviewed`
  - `@rfcbot concern <name>`
  - `@rfcbot resolve <name>` or `@rfcbot resolved <name>`
- **Bot tracking comment.** It is **edited in place**, so you see only its final state:

  ```
  Team member @joshtriplett has proposed to merge this. The next step is review by the rest of the tagged team members:
  * [x] @cramertj
  * [ ] @pnkfelix
  Concerns:
  * ~~clarify-grammar~~ resolved by https://github.com/rust-lang/rfcs/pull/3137#issuecomment-870746951
  ```

  Or `No concerns currently listed.`
- **Bot milestone comments:**
  - `:bell: **This is now entering its final comment period** …`
  - `The final comment period, with a disposition to **merge** … is now **complete**.`
- **Model mapping:**
  - Final checkboxes → `APPROVED` (no time).
  - `reviewed` commands → `APPROVED {at}`.
  - `concern` / `resolve` commands → `Concern {raised_at, resolved_at, resolved_by_url}`.
  - Bot milestones → `Decision` events (fcp_start, fcp_complete).

**Real Rust supersede/amend chains**, found by regex over RFC text: 20 RFCs, which need manual verification.

| RFC | Relation | Targets |
|---|---|---|
| 3498 Lifetime capture rules 2024 | supersedes | 1522, 2071, 3425 *(best Rust hero: `impl Trait`, T-lang)* |
| 3058 try-trait-v2 | replaces | 1859 |
| 2514 union initialization and drop | replaces | 1444 |
| 3516 public/private dependencies | supersedes | 1977 |
| 3085 edition 2021 | supersedes | 2052 |
| 3501 edition 2024 | amends | 3085 |
| 2532 associated type defaults | supersedes | 192 |
| 1201 naked fns | superseded by | 2972 |

**Rust demo slice (if used):** T-lang, plus RFCs 3498, 1522, 2071, 3425, 3137, 3681, 3058 and 1859.

## 3. Decision

- **Primary corpus: Python.**
  - It has formal `superseded_by` metadata, so the ripple uses real data with no regex guessing.
  - Its discussion threads are anonymous JSON.
  - Its Experts Index is a clean declared-ownership source.
- **Rust is the stretch adapter** and is valuable for **multi-tenancy**: "two companies, two isolated graphs, one FalkorDB" (`lineage:company:python`, `lineage:company:rust`).
  - It has the richest per-person decision data in the open-source world (rfcbot).
  - Skip Zulip, because its API needs a login. GitHub PR discussion threads serve as the "chat".

## 4. Accounts and keys needed

| What | Why | When | Cost |
|---|---|---|---|
| **Anthropic API key** (console.anthropic.com) | Historian answers + eval judge | Before Oct 15 | Pay-as-you-go; a $10–20 credit covers the event |
| **GitHub personal access token**, fine-grained, **public repositories read-only**, no scopes beyond that | CPython commits/PR search, RFC comments. Unauthenticated is 60 req/h | Before Oct 15 | Free |
| **GitHub account** for the public submission repo | Submission requirement | Have it | Free |
| **Railway** (or Fly/Render) | Host FalkorDB (with volume) + FastAPI | Before Oct 18 | Hobby plan ~$5/mo; trial credits may suffice |
| **Vercel** | Host Next.js UI | Before Oct 18 | Free |
| **WeMakeDevs account** + hackathon registration | Required to submit | Now | Free |
| **FalkorDB Discord** | Help + the ACL bug report | Now | Free |
| Optional: FalkorDB Cloud | Not needed (free tier has no persistence) | Skip | – |
| Optional: Zulip account | Only if adding Rust chat later | Skip | Free |
| Not needed | Embeddings run locally (fastembed), so no OpenAI/Voyage key | – | – |

**Store keys in a password manager.** On Oct 15 they go into a git-ignored `.env`. Never commit them.
