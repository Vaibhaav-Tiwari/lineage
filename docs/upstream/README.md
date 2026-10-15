# Findings for FalkorDB (drafts, not posted)

Three things we found in FalkorDB 6.0.2 while building Lineage. Each file has the full story (what happened, how we
found it, the evidence, what it meant for us and how we worked around it), then a ready-to-post issue and a short
main comment. **Nothing here has been posted.** Each one goes out only after an explicit OK.

| # | Finding | Severity | Reproducible | File |
|---|---|---|---|---|
| 1 | An aggregation grouped by a value and then a null can crash the whole server (Rust panic in `reply.rs:655`) | **High**: one read query takes the server down | Yes, deterministic on a fresh server | [falkordb-null-grouping-crash.md](falkordb-null-grouping-crash.md) |
| 2 | The documented read-only ACL (`%R~pattern`) refuses `GRAPH.RO_QUERY`, so the docs' own examples do not work | Medium: the documented isolation recipe fails | Yes, deterministic | [falkordb-acl-readonly-issue.md](falkordb-acl-readonly-issue.md) |
| 3 | `GRAPH.UDF LOAD REPLACE` is not atomic: queries running at that moment fail with `Unknown function` | Low/medium: transient query errors during a deploy | Yes, under concurrency | [falkordb-udf-replace-race.md](falkordb-udf-replace-race.md) |

Environment for all three: Docker image `falkordb/falkordb:6.0.2` (graph module `60002`), `redis_version:8.10.2`,
macOS on Apple Silicon (linux/arm64 container), Python client `falkordb` (async).
