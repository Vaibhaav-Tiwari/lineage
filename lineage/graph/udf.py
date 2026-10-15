"""JavaScript UDFs loaded into FalkorDB (GRAPH.UDF LOAD), so the scoring runs inside the graph query.

lineage.recency(dates, asOf, halfLifeDays)  each commit counts 0.5^(age / half-life); later than asOf counts 0
lineage.in_window(dates, from, to)          how many commits fall in [from, to]
lineage.last_before(dates, to)              the latest date not after `to` (or null)

UDFs are global to the server, so the admin connection (re)loads them at start-up.
"""

LIBRARY = "lineage"

SOURCE = """
function recency(dates, asOf, halfLife) {
  if (!dates) return 0.0;
  var t = Date.parse(asOf), s = 0.0;
  for (var i = 0; i < dates.length; i++) {
    var d = Date.parse(dates[i]);
    if (d <= t) s += Math.pow(0.5, (t - d) / 86400000 / halfLife);
  }
  return s;
}
function in_window(dates, from, to) {
  if (!dates) return 0;
  var a = Date.parse(from), b = Date.parse(to), n = 0;
  for (var i = 0; i < dates.length; i++) { var d = Date.parse(dates[i]); if (d >= a && d <= b) n++; }
  return n;
}
function last_before(dates, to) {
  if (!dates) return null;
  var b = Date.parse(to), best = null;
  for (var i = 0; i < dates.length; i++) { if (Date.parse(dates[i]) <= b && (best === null || dates[i] > best)) best = dates[i]; }
  return best;
}
falkor.register('recency', recency);
falkor.register('last_before', last_before);
falkor.register('in_window', in_window);
"""


async def ensure_udfs(db) -> None:
    await db.connection.execute_command("GRAPH.UDF", "LOAD", "REPLACE", LIBRARY, SOURCE)
