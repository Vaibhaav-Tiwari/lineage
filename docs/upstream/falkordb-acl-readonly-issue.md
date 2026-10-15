# Draft issue for FalkorDB (not posted)

Target: https://github.com/FalkorDB/FalkorDB/issues (or the docs repo, if they prefer a docs fix).
Status: **draft, waiting for approval before anything is posted.**

---

**Title:** Read-only graph ACLs from the docs (`%R~pattern`) refuse `GRAPH.RO_QUERY` on 6.0.2

### Summary

The ACL page ([docs.falkordb.com/commands/acl](https://docs.falkordb.com/commands/acl)) describes `%R~<pattern>` as
read-only access to a graph, with two examples:

- `+@all ~app1:* %R~app2:*`: full access to `app1:*`, read-only access to `app2:*`
- `ACL SETUSER reader on >pass +GRAPH.RO_QUERY %R~*`: a read-only user

On FalkorDB 6.0.2 both refuse a plain `GRAPH.RO_QUERY` with `NOPERM No permissions to access a key`.
It looks as if graph commands declare their key as read-write, so a read-only key pattern never matches.

### Environment

- Docker image `falkordb/falkordb:6.0.2` (`MODULE LIST`: `graph`, ver `60002`)
- `redis_version:8.10.2`

### Steps to reproduce

```
GRAPH.QUERY app2:users "CREATE (:U)"

ACL SETUSER reader_doc on >pass +GRAPH.RO_QUERY %R~*
AUTH reader_doc pass
GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)"
-> NOPERM No permissions to access a key

ACL SETUSER rw_doc on >pass +@all ~app1:* %R~app2:*
AUTH rw_doc pass
GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)"
-> NOPERM No permissions to access a key
```

`ACL LOG` shows `reason: key`, `object: app2:users`.

### Expected

`GRAPH.RO_QUERY` succeeds; `GRAPH.QUERY` with a write clause is refused.

### Workaround that works on 6.0.2

A Redis 7+ ACL *selector* that grants only `GRAPH.RO_QUERY` on the read-only pattern:

```
ACL SETUSER agent on >pass resetkeys -@all +@connection +INFO \
    ~app1:* +GRAPH.QUERY +GRAPH.RO_QUERY \
    (~app2:* +GRAPH.RO_QUERY)
```

Verified: `GRAPH.RO_QUERY app2:users …` returns data; `GRAPH.QUERY app2:users "CREATE …"` is refused (`NOPERM`); and a
write sent through `GRAPH.RO_QUERY` is rejected by the engine itself. `+INFO` is needed because the client calls `INFO`
on connect. `ACL DRYRUN <user> GRAPH.RO_QUERY app2:users …` is a safe way to check a rule set without running anything.

### Suggestion

Either declare the read-only key spec for `GRAPH.RO_QUERY` (and other read commands) so `%R~` works as documented,
or update the ACL page to show the selector form until it does. Happy to open a docs PR with the selector example.

### Context

Found while building per-agent memory isolation on FalkorDB for the Graph Hacks hackathon (each AI agent gets its own
graph and its own database login; agents may read the company graph but never write it). Source:
https://github.com/Vaibhaav-Tiwari/lineage (`lineage/db.py`, `lineage/security.py`).
