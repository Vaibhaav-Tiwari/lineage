# Finding 3: `GRAPH.UDF LOAD REPLACE` is not atomic

**Status:** draft, not posted. **Severity:** low to medium: queries that call a UDF fail transiently while the
library is being replaced, for example during a rolling deploy. **Reproducible:** yes, under concurrency.

## What we encountered

Lineage scores how recent each person's work on a module is with a JavaScript UDF (`lineage.recency`), so the scoring
runs inside the graph query. Our services reloaded the library with `GRAPH.UDF LOAD REPLACE` every time they started.
While investigating finding 1 we stress-tested that reload, because the crash log showed a QuickJS assertion. The
reload did not crash anything (finding 1 was a separate bug). It did show that a query calling the function can fail
in the middle of a replace.

## How we found it

In a throwaway container, one client replaced the library in a tight loop while six clients ran a query that calls
its functions over 2,000 nodes, for 60 seconds:

```
reloads: 29,696      queries: ~10,100
query errors: "Unknown function 'repro.recency'" x3, "Unknown function 'repro.last_before'" x3
```

The library was replaced with identical code every time, so the function should always exist.

## What it meant for us, and the workaround

A query arriving during a reload fails instead of seeing either the old or the new library. We now load the library
only when it is missing or its code changed: `GRAPH.UDF LIST <lib> WITHCODE`, compare, then `LOAD` or `LOAD REPLACE`
(`lineage/graph/udf.py`). UDFs persist in the snapshot across restarts, so they rarely need reloading at all.

---

## Ready-to-post issue

**Repository:** https://github.com/FalkorDB/FalkorDB/issues

**Title:** `GRAPH.UDF LOAD REPLACE` is not atomic: concurrent queries fail with `Unknown function`

**Body:**

> ### Summary
>
> While a library is being replaced with `GRAPH.UDF LOAD REPLACE`, queries that call its functions can fail with
> `Unknown function '<lib>.<fn>'`, even when the new code defines the same functions.
>
> ### Reproduction
>
> 1. `GRAPH.UDF LOAD repro "function recency(d, a, h) { ... } falkor.register('recency', recency);"`
> 2. `GRAPH.QUERY g "UNWIND range(1, 2000) AS i CREATE (:N {dates: ['2025-01-01','2025-06-01']})"`
> 3. Client A loops on `GRAPH.UDF LOAD REPLACE repro "<same code>"`.
> 4. Clients B to G loop on `GRAPH.RO_QUERY g "MATCH (n:N) RETURN sum(repro.recency(n.dates, '2026-10-16', 180))"`.
>
> Over 60 s: 29,696 replaces and about 10,100 queries, 6 of which failed with `Unknown function 'repro.recency'` (or
> another function from the same library).
>
> ### Expected
>
> A replace is atomic: a query sees either the old library or the new one.
>
> ### Environment
>
> `falkordb/falkordb:6.0.2` (module ver 60002), `redis_version:8.10.2`.

## Main comment

> Small one we noticed while load-testing UDFs on 6.0.2: replacing a library is not atomic, so a query that lands
> mid-replace gets `Unknown function`. Easy to work around (only replace when the code changed), but it bites during
> deploys. The repro numbers are in the issue.
