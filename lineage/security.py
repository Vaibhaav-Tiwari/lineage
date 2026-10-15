"""Prove the boundaries between agents, live, without changing anything.

Reads are really run with the agent's own login. Anything that would write or destroy is asked of the
database's permission engine with ACL DRYRUN instead, so a misconfiguration would show up as a failed
check, never as a deleted graph.
"""

CHECKS = [
    # agent, what it tries, command (built from the graph prefix), should it be allowed?
    ("historian", "read the company graph", lambda p: ["GRAPH.RO_QUERY", f"{p}:company", "MATCH (n) RETURN count(n)"], True),
    ("historian", "write the company graph", lambda p: ["GRAPH.QUERY", f"{p}:company", "CREATE (:Probe)"], False),
    ("historian", "read the shared task board", lambda p: ["GRAPH.RO_QUERY", f"{p}:shared", "MATCH (n) RETURN count(n)"], False),
    ("historian", "delete its own memory graph", lambda p: ["GRAPH.DELETE", f"{p}:agent:historian"], False),
    ("historian", "copy the company graph", lambda p: ["GRAPH.COPY", f"{p}:company", f"{p}:copied"], False),
    ("historian", "list every key in the database", lambda p: ["KEYS", "*"], False),
    ("steward", "mark proposals stale in the company graph", lambda p: ["GRAPH.QUERY", f"{p}:company", "MATCH (n:PEP) RETURN count(n)"], True),
    ("steward", "copy the company graph into a what-if fork", lambda p: ["GRAPH.COPY", f"{p}:company", f"{p}:company:fork:check"], True),
    ("steward", "delete a what-if fork", lambda p: ["GRAPH.DELETE", f"{p}:company:fork:check"], True),
    ("steward", "copy the company graph anywhere else", lambda p: ["GRAPH.COPY", f"{p}:company", f"{p}:elsewhere"], False),
    ("steward", "delete the company graph", lambda p: ["GRAPH.DELETE", f"{p}:company"], False),
    ("steward", "read a user's private memory", lambda p: ["GRAPH.RO_QUERY", f"{p}:user:visitor", "MATCH (n) RETURN count(n)"], False),
]


async def security_report(admin, agents: dict, prefix: str) -> list[dict]:
    """agents: name -> (acl user, that user's own connection)."""
    rows = []
    for agent, check, build, expected in CHECKS:
        if agent not in agents:
            continue
        user, conn = agents[agent]
        cmd = build(prefix)
        if expected and cmd[0] == "GRAPH.RO_QUERY":  # harmless: really run it as the agent
            try:
                await conn.connection.execute_command(*cmd)
                allowed, how, detail = True, "ran it as the agent", "OK"
            except Exception as e:
                allowed, how, detail = False, "ran it as the agent", str(e)
        else:
            out = await admin.connection.execute_command("ACL", "DRYRUN", user, *cmd)
            out = out.decode() if isinstance(out, bytes) else str(out)
            allowed, how, detail = out == "OK", "asked the permission engine (ACL DRYRUN)", out
        rows.append({"agent": agent, "check": check, "command": " ".join(cmd[:2]), "expected": expected,
                     "allowed": allowed, "ok": allowed == expected, "how": how, "detail": detail})
    return rows
