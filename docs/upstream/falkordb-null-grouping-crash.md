# Finding 1: an aggregation grouped by a value and then a null crashes the server

**Status:** already reported upstream by others as [FalkorDB/FalkorDB#3150](https://github.com/FalkorDB/FalkorDB/issues/3150)
(open since 30 Sep 2026, confirmed on 6.0.1 and 6.0.2), with a fix in review in
[FalkorDB/FalkorDB#3229](https://github.com/FalkorDB/FalkorDB/pull/3229). **Do not open a new issue**: at most, add the
main comment below to #3150. Not posted. **Severity:** high: a single query, read-only included, takes the whole server
down (every graph, every client). **Reproducible:** yes, every time on a freshly started server.

## What we encountered

On 16 Oct 2026, our FalkorDB container restarted twice while running a benchmark script. Every client lost its
connection (`redis.exceptions.ConnectionError: Connection closed by server`); an evaluation running in another process
failed at the same moment. The container came back by itself (we run it with `--restart unless-stopped`) and reloaded
the last snapshot, so no data was lost: the most recent snapshot was seconds old.

## How we found the cause

1. **The server log.** Each crash starts with a Rust panic, followed by Redis's crash report:

   ```
   # <module> FalkorDB panic: panicked at src/reply.rs:655:58:
   called `Option::unwrap()` on a `None` value
   Backtrace:
      8: core::option::unwrap_failed
      9: falkordb::reply::reply_compact
     10: falkordb::graph_core::execute_query
     11: <falkordb::graph_core::query_mut::{closure#0} as core::ops::function::FnOnce<()>>::call_once
     12: <graph::threadpool::ThreadPool>::new::{closure#0}
   redis-server: .../rquickjs-sys-.../quickjs.c:2704: void JS_FreeRuntime(JSRuntime *):
       Assertion `list_empty(&rt->gc_obj_list)' failed.
   # Redis 8.10.2 crashed by signal: 6, si_code: -6
   ```

   We first suspected the JavaScript UDF engine because of the QuickJS assertion. The panic comes first, though, and
   the assertion fires afterwards during teardown. The real failure is in the reply encoder.

2. **Isolating it without risking our data.** We copied the database snapshot into a throwaway container on another
   port and ran our script's queries there one at a time. One read query crashed it every time:

   ```cypher
   MATCH (n {id: 'chunk:pep:380:1'})
   OPTIONAL MATCH (n)-[:PART_OF]->(pp:PEP) WITH n, pp AS p
   OPTIONAL MATCH (a:Person)-[:AUTHORED]->(p)
   OPTIONAL MATCH (r:PEP)-[:SUPERSEDES]->(p)
   OPTIONAL MATCH (w:Person)-[:POSTED]->(n)
   RETURN n.id, p.number, p.title, p.status, toString(p.created),
          collect(DISTINCT coalesce(a.name, a.github)), collect(DISTINCT r.number),
          head(collect(DISTINCT coalesce(w.name, w.github))), toString(n.created)
   ```

   Removing any single return item stopped the crash, which pointed at the shape of the grouping keys rather than
   one expression. `toString(n.created)` is null for that node, and replacing it with a constant also stopped the crash.

3. **A minimal case.** On an empty server:

   ```
   GRAPH.QUERY g "CREATE (:N {id:'x'})"
   GRAPH.QUERY g "MATCH (n:N) RETURN n.id, null, count(*)"
   ```

   On a freshly started server this crashes every time we tried. It crashes with `GRAPH.QUERY` and `GRAPH.RO_QUERY`,
   with and without `--compact`, with `count(*)` or `collect(...)`, and with a literal `null` or a missing property.
   **Putting the null key first does not crash:** `RETURN n.missing, n.id, collect(1)` returns normally.

## What we could not pin down

The rule is narrower than "any null grouping key". Several of our production queries group by a nullable column after
a non-null one, for example `RETURN n.id, labels(n)[0], n.status, coalesce(n.stale, false), n.stale_because, collect(s.id)`.
They ran for days, and on a fresh server, without crashing. A constant-only `RETURN 1, null, collect(1)` with no
`MATCH` does not crash either. So the trigger needs records from a `MATCH`, a non-null key before a null key, and an
aggregation, plus something about the result shape that we did not isolate.

## What it meant for us, and the workaround

- **Impact:** any client could take down every graph on the server, which for us means every agent's memory, the
  company graph and the shared board.
- **Workaround:** grouping keys that can be null are wrapped in `coalesce(..., '')` (see `eval/baseline.py`, `DOC_META`).
  The container's restart policy plus a recent snapshot meant we lost nothing.

---

## Issue text (kept for reference; the issue already exists as #3150)

**Repository:** https://github.com/FalkorDB/FalkorDB/issues

**Title:** Server crash (panic in `reply.rs:655`, `Option::unwrap()` on `None`) on aggregation grouped by a value then a null

**Body:**

> ### Summary
>
> A query that aggregates while grouping by a non-null value followed by a null crashes the server with a Rust panic in
> `reply.rs`. Redis then aborts with a QuickJS assertion during teardown. Every client loses its connection. It
> happens with read-only queries too.
>
> ### Minimal reproduction (fresh server)
>
> ```
> docker run -p 6379:6379 falkordb/falkordb:6.0.2
> redis-cli GRAPH.QUERY g "CREATE (:N {id:'x'})"
> redis-cli GRAPH.QUERY g "MATCH (n:N) RETURN n.id, null, count(*)"
> ```
>
> The second command fails with `Error: Server closed the connection` and the server process exits (verified on a
> fresh `falkordb/falkordb:6.0.2` container on 16 Oct 2026).
>
> Also crashes with: `GRAPH.RO_QUERY`; with or without `--compact`; `collect(1)` instead of `count(*)`; `n.missing`
> (a missing property) instead of the literal `null`.
>
> Does **not** crash: `MATCH (n:N) RETURN n.missing, n.id, count(*)` (null key first), or `RETURN 1, null, collect(1)` (no `MATCH`).
>
> ### Log
>
> ```
> # <module> FalkorDB panic: panicked at src/reply.rs:655:58:
> called `Option::unwrap()` on a `None` value
>    9: falkordb::reply::reply_compact
>   10: falkordb::graph_core::execute_query
>   11: <falkordb::graph_core::query_mut::{closure#0} ...>::call_once
> redis-server: .../quickjs.c:2704: void JS_FreeRuntime(JSRuntime *): Assertion `list_empty(&rt->gc_obj_list)' failed.
> # Redis 8.10.2 crashed by signal: 6, si_code: -6
> ```
>
> ### Environment
>
> `falkordb/falkordb:6.0.2` (module ver 60002), `redis_version:8.10.2`, linux/arm64 container on macOS (Apple Silicon).
>
> ### Notes
>
> - We first hit it with a real 9-column query on a server that had been running for hours, so it is not limited to
>   fresh servers. The minimal case above is just the shortest one we found.
> - Some queries with a null grouping key after a non-null one do not crash, so the exact condition is narrower than
>   this description. We are happy to share the longer query and a dataset if that helps.
> - Workaround: `coalesce()` nullable grouping keys.

## Main comment (for #3150)

> Hi FalkorDB team! While building on 6.0.2 for Graph Hacks we found a query that panics the server
> (`reply.rs:655`, unwrap on `None`). The minimal repro is three commands on an empty container: a value then a
> `null` as grouping keys, plus `count(*)`. It takes down every graph on the server, so we thought it worth flagging
> quickly. Full details are in the issue above; happy to test a fix.
