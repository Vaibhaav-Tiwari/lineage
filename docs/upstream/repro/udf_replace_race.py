"""Reproduce: GRAPH.UDF LOAD REPLACE is not atomic. Queries that call the library while it is being replaced
(with identical code) fail with "Unknown function". Runs against a fresh, throwaway container and removes it.

    uv run python docs/upstream/repro/udf_replace_race.py | tee docs/upstream/evidence/udf_replace_race.txt
"""

import asyncio
import os
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone

import redis.asyncio as redis

IMG = os.environ.get("IMG", "falkordb/falkordb:6.0.2")
NAME, PORT, SECONDS, READERS = "udf-race-repro", 6394, 60, 6
LIB = """
function recency(dates, asOf, halfLife) {
  var t = Date.parse(asOf), s = 0.0;
  for (var i = 0; i < dates.length; i++) { var d = Date.parse(dates[i]); if (d <= t) s += Math.pow(0.5, (t - d) / 86400000 / halfLife); }
  return s;
}
falkor.register('recency', recency);
"""
QUERY = "MATCH (n:N) RETURN sum(repro.recency(n.dates, '2026-10-16', 180))"


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout


async def main():
    sh("docker", "rm", "-f", NAME)
    sh("docker", "run", "-d", "--name", NAME, "-p", f"127.0.0.1:{PORT}:6379", IMG)
    r = redis.Redis(port=PORT, decode_responses=True)
    for _ in range(30):
        try:
            await r.ping(); break
        except Exception:
            time.sleep(1)
    info = await r.info("server")
    mods = await r.execute_command("MODULE", "LIST")
    graph_ver = "?"
    for m in mods:
        d = m if isinstance(m, dict) else dict(zip(m[::2], m[1::2]))
        if d.get("name") == "graph":
            graph_ver = d.get("ver")
    print(f"# Environment ({datetime.now(timezone.utc).isoformat(timespec='seconds')})")
    print(f"image: {IMG}\nredis_version: {info['redis_version']}\ngraph module: {graph_ver}\n")

    print("# Setup")
    print('$ GRAPH.UDF LOAD repro "<library defining repro.recency>"')
    print(" ", await r.execute_command("GRAPH.UDF", "LOAD", "repro", LIB))
    print("$ GRAPH.QUERY g \"UNWIND range(1, 2000) AS i CREATE (:N {dates: ['2025-01-01','2025-06-01','2026-01-01']})\"")
    await r.execute_command("GRAPH.QUERY", "g", "UNWIND range(1, 2000) AS i CREATE (:N {dates: ['2025-01-01','2025-06-01','2026-01-01']})")
    print(f"$ GRAPH.RO_QUERY g \"{QUERY}\"")
    print(" ", (await r.execute_command("GRAPH.RO_QUERY", "g", QUERY))[1][0][0])

    print(f"\n# For {SECONDS} s: 1 client replaces the library with the SAME code in a loop; {READERS} clients run the query in a loop")
    stop = time.time() + SECONDS
    errors, first = Counter(), []

    async def replacer():
        c, n = redis.Redis(port=PORT, decode_responses=True), 0
        while time.time() < stop:
            await c.execute_command("GRAPH.UDF", "LOAD", "REPLACE", "repro", LIB); n += 1
        return n

    async def reader():
        c, n = redis.Redis(port=PORT, decode_responses=True), 0
        while time.time() < stop:
            try:
                await c.execute_command("GRAPH.RO_QUERY", "g", QUERY); n += 1
            except redis.ResponseError as e:
                errors[str(e)] += 1
                if len(first) < 3:
                    first.append(f"{datetime.now(timezone.utc).isoformat(timespec='milliseconds')}  {e}")
        return n

    reloads, *reads = await asyncio.gather(replacer(), *(reader() for _ in range(READERS)))
    print(f"replaces: {reloads:,}\nsuccessful queries: {sum(reads):,}\nfailed queries: {sum(errors.values())}")
    for msg, n in errors.items():
        print(f"  {n} x  {msg}")
    if first:
        print("first failures:")
        for f in first:
            print("  " + f)
    print("\nExpected: 0 failed queries (a replace with identical code should be atomic).")
    sh("docker", "rm", "-f", NAME)
    print("\n# Done: throwaway container removed")


asyncio.run(main())
