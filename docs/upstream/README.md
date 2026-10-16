# Findings for FalkorDB

Three things we found in FalkorDB 6.0.2 while building Lineage. Each file has the full story (what happened, how we
found it, the evidence, what it meant for us and how we worked around it), then a ready-to-post issue and a short
main comment. **Reported on 16 Oct 2026:** finding 2 as [FalkorDB/FalkorDB#3356](https://github.com/FalkorDB/FalkorDB/issues/3356),
finding 3 as [FalkorDB/FalkorDB#3357](https://github.com/FalkorDB/FalkorDB/issues/3357), and our data points added to
the existing finding-1 issue in [this comment](https://github.com/FalkorDB/FalkorDB/issues/3150#issuecomment-6215167947).

Before posting we checked FalkorDB's GitHub: finding 1 was already reported (see the table); findings 2 and 3 had no
existing issue or pull request. Note that the open docs pull request
[FalkorDB/docs#456](https://github.com/FalkorDB/docs/pull/456) adds more `%R~` examples of the kind finding 2 shows to fail.

| # | Finding | Severity | Reproducible | File |
|---|---|---|---|---|
| 1 | An aggregation grouped by a value and then a null can crash the whole server (Rust panic in `reply.rs:655`) | **High**: one read query takes the server down | Yes, deterministic on a fresh server | [falkordb-null-grouping-crash.md](falkordb-null-grouping-crash.md). **Already reported** as [FalkorDB/FalkorDB#3150](https://github.com/FalkorDB/FalkorDB/issues/3150), fix in review in [FalkorDB/FalkorDB#3229](https://github.com/FalkorDB/FalkorDB/pull/3229): add a comment, do not open a new issue |
| 2 | The documented read-only ACL (`%R~pattern`) refuses `GRAPH.RO_QUERY`, so the docs' own examples do not work | Medium: the documented isolation recipe fails | Yes, deterministic | [falkordb-acl-readonly-issue.md](falkordb-acl-readonly-issue.md) |
| 3 | `GRAPH.UDF LOAD REPLACE` is not atomic: queries running at that moment fail with `Unknown function` | Low/medium: transient query errors during a deploy | Yes, under concurrency | [falkordb-udf-replace-race.md](falkordb-udf-replace-race.md) |

Environment for all three: Docker image `falkordb/falkordb:6.0.2` (graph module `60002`), `redis_version:8.10.2`,
macOS on Apple Silicon (linux/arm64 container), Python client `falkordb` (async).
