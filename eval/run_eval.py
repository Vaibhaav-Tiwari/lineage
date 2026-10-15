"""Evaluate the Historian against ground truth from the real graph.

    uv run python -m eval.run_eval --backend claude-code [--limit N]
    uv run python -m eval.run_eval --backend graph-only

Scoring is deterministic (no LLM judge): a fact passes if any accepted phrasing
appears in the answer; citation recall = expected ids cited / expected ids;
out-of-corpus questions must abstain. Ripple accuracy is measured on a
GRAPH.COPY fork so the live graph is never modified.
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import date
from pathlib import Path

import yaml

from lineage.agents.historian import ask
from lineage.db import get_db
from lineage.graph.ripple import company_ripple
from lineage.ingest.events import mark_event_applied
from lineage.schema import ensure_agent_schema

HERE = Path(__file__).parent


def judge(q: dict, text: str, citations: list[str], abstained: bool) -> dict:
    if q.get("expect_abstain"):
        return {"correct": abstained, "citation_recall": None, "missing": [] if abstained else ["should abstain"]}
    low = (text or "").lower()
    missing = [alts[0] for alts in q.get("facts", []) if not any(a.lower() in low for a in alts)]
    exp = q.get("expected_ids") or []
    recall = (len(set(exp) & set(citations)) / len(exp)) if exp else None
    return {"correct": not abstained and not missing, "citation_recall": recall, "missing": missing}


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else 0.0


async def _ripple_accuracy(db, prefix: str, spec: dict) -> dict | None:
    if not spec:
        return None
    company = db.select_graph(f"{prefix}:company")
    fork_name = f"{prefix}:company:fork:eval{uuid.uuid4().hex[:6]}"
    await company.copy(fork_name)
    fork = db.select_graph(fork_name)
    try:
        changed = await mark_event_applied(fork, spec["event"])
        r = await company_ripple(fork, changed, "eval")
    finally:
        await fork.delete()
    expected, got = set(spec["expected_soft"]), set(r["soft"])
    return {"expected": len(expected), "found": len(got), "recall": len(expected & got) / len(expected),
            "precision": (len(expected & got) / len(got)) if got else 0.0, "extra": sorted(got - expected),
            "missed": sorted(expected - got)}


def summarize(rows: list[dict], qs: list[dict]) -> tuple[dict, dict]:
    tool_ms: dict[str, list[float]] = {}
    for r in rows:
        for name, ms in r.get("tool_ms", []):
            tool_ms.setdefault(name, []).append(ms)
    asked = {r["q"] for r in rows}
    answerable = [r for r in rows if r["citation_recall"] is not None]
    summary = {
        "n": len(rows), "correct": sum(r["correct"] for r in rows),
        "accuracy": sum(r["correct"] for r in rows) / len(rows) if rows else 0,
        "citation_recall": statistics.mean(r["citation_recall"] for r in answerable) if answerable else None,
        "abstention": f"{sum(r['correct'] for r in rows if r['citation_recall'] is None and 'should abstain' not in r['missing'])}"
                      f"/{sum(1 for q in qs if q.get('expect_abstain') and q['q'] in asked)}",
        "median_seconds": statistics.median(r["seconds"] for r in rows) if rows else 0,
    }
    latency = {k: {"calls": len(v), "p50": round(_pct(v, 0.5), 1), "p95": round(_pct(v, 0.95), 1)} for k, v in sorted(tool_ms.items())}
    return summary, latency


async def run_eval(db, prefix: str, questions: dict, llm_factory, embedder, limit: int | None = None,
                   offset: int = 0) -> dict:
    allq = questions["questions"][offset:]
    qs = allq[:limit] if limit else allq
    company = db.select_graph(f"{prefix}:company")
    agent = db.select_graph(f"{prefix}:agent:eval")
    if agent.name in await db.list_graphs():
        await agent.delete()
    await ensure_agent_schema(agent)
    rows = []
    try:
        for q in qs:
            t0 = time.perf_counter()
            r = await ask(q["q"], company_g=company, agent_g=agent, user_g=None, llm=llm_factory(), embedder=embedder,
                          as_of=date.fromisoformat(q["as_of"]) if q.get("as_of") else None)
            wall = time.perf_counter() - t0
            j = judge(q, r.text, r.citations, r.abstained)
            rows.append({"q": q["q"], **j, "abstained": r.abstained, "seconds": round(wall, 1),
                         "tools": len(r.tool_trace), "error": r.usage.get("error"),
                         "tool_ms": [[t["name"], t["ms"]] for t in r.tool_trace]})
    finally:
        await agent.delete()
    summary, latency = summarize(rows, qs)
    ripple = await _ripple_accuracy(db, prefix, questions.get("ripple"))
    return {"rows": rows, "summary": summary, "latency": latency, "ripple": ripple}


def render_markdown(res: dict, backend: str) -> str:
    s = res["summary"]
    out = [f"# Evaluation — backend `{backend}`", "",
           f"- **Correct:** {s['correct']}/{s['n']} ({s['accuracy']:.0%})",
           f"- **Citation recall** (answerable questions): {s['citation_recall']:.0%}" if s["citation_recall"] is not None else "- **Citation recall:** n/a",
           f"- **Correct abstentions** on out-of-corpus questions: {s['abstention']}",
           f"- **Median time per question:** {s['median_seconds']} s", ""]
    rp = res["ripple"]
    out.append(f"- **Ripple recall:** {rp['recall']:.0%}, precision {rp['precision']:.0%} "
               f"({rp['found']} PEPs flagged, {rp['expected']} expected; missed {rp['missed'] or 'none'}, extra {rp['extra'] or 'none'})"
               if rp else "- **Ripple recall:** not measured (no ripple spec)")
    out += ["", "## Graph tool latency (ms)", "", "| Tool | Calls | p50 | p95 |", "|---|---|---|---|"]
    out += [f"| {k} | {v['calls']} | {v['p50']} | {v['p95']} |" for k, v in res["latency"].items()]
    out += ["", "## Questions", "", "| Question | Correct | Citation recall | Missing | Seconds |", "|---|---|---|---|---|"]
    for r in res["rows"]:
        rec = "–" if r["citation_recall"] is None else f"{r['citation_recall']:.0%}"
        miss = ", ".join(r["missing"]) or ("–" if not r["error"] else f"error: {r['error'][:60]}")
        out.append(f"| {r['q']} | {'✅' if r['correct'] else '❌'} | {rec} | {miss} | {r['seconds']} |")
    return "\n".join(out) + "\n"


async def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="claude-code", choices=["claude-code", "graph-only", "anthropic"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--merge", action="store_true", help="merge with rows saved by earlier runs of this backend")
    ap.add_argument("--prefix", default="lineage")
    a = ap.parse_args()
    from lineage.agents.backends import make_llm
    from lineage.ingest.embed import Embedder

    db = await get_db()
    questions = yaml.safe_load((HERE / "questions.yaml").read_text())
    res = await run_eval(db, a.prefix, questions, llm_factory=lambda: make_llm(a.backend), embedder=Embedder(),
                         limit=a.limit, offset=a.offset)
    store = HERE / f"results-{a.backend}.json"
    if a.merge and store.exists():
        old = {r["q"]: r for r in json.loads(store.read_text())}
        old.update({r["q"]: r for r in res["rows"]})
        order = [q["q"] for q in questions["questions"]]
        res["rows"] = sorted(old.values(), key=lambda r: order.index(r["q"]) if r["q"] in order else 999)
        res["summary"], res["latency"] = summarize(res["rows"], questions["questions"])
    store.write_text(json.dumps(res["rows"], indent=1))
    md = render_markdown(res, a.backend)
    (HERE / f"results-{a.backend}.md").write_text(md)
    print(md)
    await db.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
