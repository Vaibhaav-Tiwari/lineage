"""Plain search vs Lineage, on the same data.

"Plain search" is what most company-brain retrieval does: vector search plus full-text search over the same
passages and forum posts, with the same embeddings, merged by reciprocal rank fusion. It has no graph, no dates
and no stale flags, but each hit carries the metadata a normal document store keeps (the PEP header with status
and Superseded-By, a post's author and date). It is scored generously: a question counts as answered if the facts appear
anywhere in its top 5 results (as if a perfect reader read them).

Two tests:
  A. the 20 eval questions (eval/questions.yaml), against Lineage's saved results for both backends;
  B. currency: for every proposal Python marked as superseded, search its title the way a user would.
     Does the top result hand you the replaced proposal with nothing saying so, and does the replacement
     appear at all? Lineage (graph-only, deterministic) is asked "Is PEP N still current?".

    uv run python -m eval.baseline
"""

import asyncio
import json
from pathlib import Path

import yaml

from lineage.db import get_db, ro
from lineage.graph import queries as Q

HERE = Path(__file__).parent
K, RRF = 5, 60
SUPERSEDED = """
MATCH (s:PEP)<-[:SUPERSEDES]-(r:PEP)
RETURN s.number AS number, s.title AS title, s.status AS status, collect(DISTINCT r.number) AS by
ORDER BY s.number
"""


async def plain_search(g, embedder, query: str, k: int = K) -> list[dict]:
    """Vector + full-text over passages and posts, fused by rank. No graph, no time, no status."""
    vec = embedder.embed([query])[0]
    lists = [
        await ro(g, Q.VECTOR_CHUNKS, {"k": 20, "q": vec, "as_of": None}),
        await ro(g, Q.VECTOR_POSTS, {"k": 20, "q": vec, "as_of": None}),
    ]
    for cypher in (Q.FULLTEXT_CHUNKS, Q.FULLTEXT_PEP_TITLES):
        try:
            lists.append(await ro(g, cypher, {"q": query, "k": 20, "as_of": None}))
        except Exception:  # full-text syntax can reject some punctuation; plain search just skips it
            lists.append([])
    score: dict[str, float] = {}
    hit: dict[str, dict] = {}
    for rows in lists:
        for rank, r in enumerate(rows):
            score[r["id"]] = score.get(r["id"], 0.0) + 1.0 / (RRF + rank + 1)
            hit.setdefault(r["id"], r)
    return await with_metadata(g, [hit[i] for i in sorted(score, key=lambda i: -score[i])[:k]])


# What a normal document store keeps with each hit: the PEP file's header, and a post's author and date.
DOC_META = """
UNWIND $ids AS id
MATCH (n {id: id})
OPTIONAL MATCH (n)-[:PART_OF]->(pp:PEP)
OPTIONAL MATCH (n)-[:IN]->(:Thread)<-[:DISCUSSED_IN]-(tp:PEP)
WITH n, coalesce(pp, tp, CASE WHEN n:PEP THEN n END) AS p
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(p)
OPTIONAL MATCH (r:PEP)-[:SUPERSEDES]->(p)
OPTIONAL MATCH (w:Person)-[:POSTED]->(n)
// grouping keys are never null: FalkorDB 6.0.2 can crash on an aggregation grouped by a value then a null
// (see docs/upstream/falkordb-null-grouping-crash.md)
RETURN n.id AS id, coalesce(p.number, -1) AS number, coalesce(p.title, '') AS title, coalesce(p.status, '') AS status,
       coalesce(toString(p.created), '') AS created, coalesce(toString(n.created), '') AS posted,
       collect(DISTINCT coalesce(a.name, a.github)) AS authors, collect(DISTINCT r.number) AS superseded_by,
       head(collect(DISTINCT coalesce(w.name, w.github))) AS poster
"""


async def with_metadata(g, hits: list[dict]) -> list[dict]:
    meta = {m["id"]: m for m in await ro(g, DOC_META, {"ids": [h["id"] for h in hits]})}
    out = []
    for h in hits:
        m = meta.get(h["id"], {})
        head = (f"PEP {m.get('number')}: {m.get('title')}. Author: {', '.join(m.get('authors') or [])}. "
                f"Status: {m.get('status')}. Created: {m.get('created')}."
                + (f" Superseded-By: {', '.join(map(str, m['superseded_by']))}." if m.get("superseded_by") else ""))
        if m.get("poster"):
            head += f" Forum post by {m['poster']} on {m.get('posted')}."
        out.append({**h, "text": f"{head} {h.get('text') or ''}"})
    return out


def _text(hits: list[dict]) -> str:
    return " ".join(f"{h.get('title') or ''} {h.get('text') or ''}" for h in hits).lower()


async def test_a(g, embedder) -> dict:
    qs = yaml.safe_load((HERE / "questions.yaml").read_text())["questions"]
    rows = []
    for q in qs:
        hits = await plain_search(g, embedder, q["q"])
        low = _text(hits)
        if q.get("expect_abstain"):
            rows.append({"q": q["q"], "kind": "out-of-corpus", "correct": False if hits else True,
                         "note": f"returned {len(hits)} passages; plain search has no notion of 'not in the archive'"})
        else:
            missing = [alts[0] for alts in q.get("facts", []) if not any(a.lower() in low for a in alts)]
            rows.append({"q": q["q"], "kind": "as-of" if q.get("as_of") else "fact", "correct": not missing,
                         "note": "facts found in top 5" if not missing else f"missing: {', '.join(missing)}"})
    saved = {}
    for backend in ("graph-only", "claude-code"):
        f = HERE / f"results-{backend}.json"
        if f.exists():
            per = json.loads(f.read_text())
            saved[backend] = sum(1 for r in per if r.get("correct"))
    return {"rows": rows, "plain_correct": sum(r["correct"] for r in rows), "total": len(rows), "lineage": saved}


async def test_b(g, embedder, agent) -> dict:
    from lineage.agents.backends import GraphOnlyLLM
    from lineage.agents.historian import ask

    class _NoEmbed:  # the graph-only Historian does not search, so it needs no embedder
        def embed(self, texts):
            return [[0.0] * 384 for _ in texts]

    rows = []
    for s in await ro(g, SUPERSEDED):
        hits = await plain_search(g, embedder, s["title"])
        top = [h.get("number") for h in hits]
        stale_top = bool(top) and top[0] == s["number"]
        low = _text(hits)
        replacement_shown = any(n in s["by"] for n in top) or "superseded-by" in low
        r = await ask(f"Is PEP {s['number']} still current?", company_g=g, agent_g=agent, user_g=None,
                      llm=GraphOnlyLLM(), embedder=_NoEmbed())
        low = r.text.lower()
        flagged = "supersed" in low and any(f"pep {n}" in low for n in s["by"])
        rows.append({"pep": s["number"], "title": s["title"], "by": s["by"], "plain_top": top[0] if top else None,
                     "plain_top_is_replaced": stale_top, "plain_shows_replacement": replacement_shown,
                     "lineage_flags_and_names_replacement": flagged})
    n = len(rows)
    return {"rows": rows, "n": n,
            "plain_top_is_replaced": sum(r["plain_top_is_replaced"] for r in rows),
            "plain_shows_replacement": sum(r["plain_shows_replacement"] for r in rows),
            "plain_misleads": sum(r["plain_top_is_replaced"] and not r["plain_shows_replacement"] for r in rows),
            "plain_top_is_current": sum(not r["plain_top_is_replaced"] for r in rows),
            "lineage_flags": sum(r["lineage_flags_and_names_replacement"] for r in rows)}


def markdown(a: dict, b: dict) -> str:
    lin = a["lineage"]
    out = [
        "# Plain search vs Lineage",
        "",
        "Generated by `uv run python -m eval.baseline`. Same data, same embeddings. **Plain search** = vector + full-text",
        "search over the same passages and forum posts, fused by rank: no graph and no stale flags, but each hit carries",
        "the metadata a normal document store keeps (the PEP header with status and Superseded-By, a post's author and date).",
        "It is scored **generously**: a question counts as answered if the facts appear anywhere in its top 5 results.",
        "",
        "## A. The 20 eval questions",
        "",
        "| | Plain search (top 5, generous) | Lineage, graph-only | Lineage, Claude |",
        "|---|---:|---:|---:|",
        f"| Correct | {a['plain_correct']}/{a['total']} | {lin.get('graph-only', '?')}/{a['total']} | {lin.get('claude-code', '?')}/{a['total']} |",
        "",
        "| Question | Kind | Plain search | Why |",
        "|---|---|---|---|",
        *[f"| {r['q']} | {r['kind']} | {'yes' if r['correct'] else 'no'} | {r['note']} |" for r in a["rows"]],
        "",
        "## B. Currency: proposals Python marked as superseded",
        "",
        f"For each of the **{b['n']}** superseded proposals, we searched its title, as someone looking for it would.",
        "",
        "| | Result |",
        "|---|---:|",
        f"| Plain search: top result is the replaced proposal | {b['plain_top_is_replaced']}/{b['n']} |",
        f"| Plain search: the replacement, or a 'Superseded-By' header, appears in the top 5 | {b['plain_shows_replacement']}/{b['n']} |",
        f"| Plain search: top result is the replaced proposal **and** the replacement is nowhere in the top 5 | {b['plain_misleads']}/{b['n']} |",
        f"| Lineage: says it was superseded **and** names the replacement | {b['lineage_flags']}/{b['n']} |",
        "",
        "With document metadata, plain search often *shows* a Superseded-By header, if the reader notices it. What it cannot",
        "do is change anything that was already concluded from the old proposal: answers, notes and actions built on it.",
        "That is the part Lineage adds, and this test does not measure it (see the un-learning demo and its tests).",
        "",
        "| PEP | Replaced by | Plain search top hit | Replacement in top 5 | Lineage flags it |",
        "|---|---|---|---|---|",
        *[f"| {r['pep']} {r['title']} | {', '.join(map(str, r['by']))} | PEP {r['plain_top']} | {'yes' if r['plain_shows_replacement'] else 'no'} | {'yes' if r['lineage_flags_and_names_replacement'] else 'no'} |" for r in b["rows"]],
        "",
        "## What this does and does not show",
        "",
        "- Test A is an **upper bound** for plain search: it assumes a perfect reader of the top 5 passages. A real",
        "  RAG system would also need an LLM to read them correctly.",
        "- Plain search has no way to say \"this is not in the archive\", so out-of-corpus questions count against it.",
        "  A real RAG system's LLM might still refuse; we did not run one.",
        "- Test B uses Python's own superseded metadata, so it measures what a graph does with an explicit status",
        "  change. It does not show that Lineage detects changes nobody recorded.",
        "",
    ]
    return "\n".join(out)


async def main():
    from lineage.graph.udf import ensure_udfs
    from lineage.ingest.embed import Embedder
    from lineage.schema import ensure_agent_schema

    embedder = Embedder()
    db = await get_db()
    await ensure_udfs(db)
    g = db.select_graph("lineage:company")
    agent = db.select_graph("lineage:agent:baseline")
    if agent.name in await db.list_graphs():
        await agent.delete()
    await ensure_agent_schema(agent)
    try:
        a = await test_a(g, embedder)
        b = await test_b(g, embedder, agent)
    finally:
        await agent.delete()
        await db.aclose()
    (HERE / "baseline.json").write_text(json.dumps({"a": a, "b": b}, indent=2, default=str))
    (HERE / "baseline.md").write_text(markdown(a, b))
    print(f"A: plain {a['plain_correct']}/{a['total']}  lineage {a['lineage']}")
    print(f"B: n={b['n']} plain_top_is_replaced={b['plain_top_is_replaced']} plain_shows_replacement={b['plain_shows_replacement']} "
          f"plain_misleads={b['plain_misleads']} lineage_flags={b['lineage_flags']}")


if __name__ == "__main__":
    asyncio.run(main())
