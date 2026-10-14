"""The Historian: answers why / who / when questions about the company from
graph evidence only, cites stable ids, abstains when no evidence path exists,
and writes what it concluded into its own memory graph."""

import json
import time
from dataclasses import dataclass, field
from datetime import date

from lineage.db import ro
from lineage.graph import queries as Q
from lineage.graph.search import hits_to_fragment, hybrid_search
from lineage.graph.subgraph import Fragment
from lineage.graph.tools import TOOL_SPECS, decision_path, pep_timeline, related_peps, who_knows
from lineage.memory.store import record_answer, record_episode

MAX_TOOL_CALLS = 6
ABSTAIN = "I couldn't find evidence in the graph for that."

SYSTEM = """You are the Historian for the Python project's "company brain": a graph of PEPs (proposals), \
decisions, the people who wrote and decided them, forum discussions, implementing pull requests, and who \
owns which part of the code.

Answer only from what the tools return. Every claim in your answer must rest on ids that appeared in a tool \
result (e.g. pep:649, decision:pep:649:accept, person:gpshead, post:96520). For WHY / WHO DECIDED questions \
use decision_path; for WHEN, pep_timeline; for WHO SHOULD I ASK, who_knows; use search when you don't yet \
know which PEP is involved. You have at most 6 tool calls.

Finish by calling submit_answer with a short, direct answer (2-6 sentences, name people and dates), the ids \
you rely on, and 1-3 beliefs you concluded with the ids each rests on and an honest confidence. If the tools \
do not contain the answer, submit an answer saying so with no citations - never guess."""


@dataclass
class AskResult:
    answer_id: str | None
    text: str
    abstained: bool
    citations: list[str]
    evidence: Fragment
    beliefs: list[dict] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"answer_id": self.answer_id, "text": self.text, "abstained": self.abstained,
                "citations": self.citations, "evidence": self.evidence.to_json(), "beliefs": self.beliefs,
                "tool_trace": self.tool_trace, "usage": self.usage}


async def _run_tool(name: str, inp: dict, company_g, embedder, as_of: date | None) -> Fragment:
    if name == "search":
        return hits_to_fragment(await hybrid_search(company_g, inp["query"], embedder, k=int(inp.get("k", 6)), as_of=as_of))
    if name == "decision_path":
        return await decision_path(company_g, int(inp["pep"]), as_of)
    if name == "pep_timeline":
        return await pep_timeline(company_g, int(inp["pep"]), as_of)
    if name == "who_knows":
        return await who_knows(company_g, str(inp["topic"]), as_of)
    if name == "related_peps":
        return await related_peps(company_g, int(inp["pep"]), int(inp.get("hops", 2)))
    raise ValueError(f"unknown tool {name}")


def _evidence(union: Fragment, cited: list[str]) -> Fragment:
    """Cited nodes plus their direct neighbours in what the tools returned."""
    keep = set(cited)
    for e in union.edges:
        if e["src"] in cited or e["dst"] in cited:
            keep |= {e["src"], e["dst"]}
    nodes = [n for n in union.nodes if n["id"] in keep]
    ids = {n["id"] for n in nodes}
    edges = [e for e in union.edges if e["src"] in ids and e["dst"] in ids]
    return Fragment(nodes, edges)


async def ask(question: str, *, company_g, agent_g, user_g, llm, embedder, as_of: date | None = None) -> AskResult:
    prompt = question if not as_of else f"{question}\n\n(Answer as of {as_of.isoformat()}: ignore anything that happened later.)"
    messages: list = [{"role": "user", "content": prompt}]
    union, trace, usage = Fragment(), [], {"input": 0, "output": 0, "cache_read": 0}
    submitted, nudged, used = None, False, 0

    for _ in range(MAX_TOOL_CALLS + 6):
        turn = await llm.complete(SYSTEM, messages, TOOL_SPECS)
        for k, v in (turn.usage or {}).items():
            usage[k] = usage.get(k, 0) + v
        messages.append({"role": "assistant", "content": turn.assistant_content})
        if turn.stop_reason == "refusal":
            break
        if not turn.tool_calls:
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": "Please call submit_answer now with your answer and the ids you cite."})
            continue
        results = []
        for c in turn.tool_calls:
            if c["name"] == "submit_answer":
                submitted = c["input"]
                results.append({"type": "tool_result", "tool_use_id": c["id"], "content": "received"})
                continue
            if used >= MAX_TOOL_CALLS:
                results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                                "content": "Tool budget used up. Call submit_answer now."})
                continue
            used += 1
            t0 = time.perf_counter()
            try:
                frag = await _run_tool(c["name"], c["input"], company_g, embedder, as_of)
                union = union.merge(frag)
                content, err = json.dumps(frag.meta, default=str)[:12000], None
            except Exception as e:  # report to the model, never crash the request
                content, err = f"Error: {e}", str(e)
            trace.append({"name": c["name"], "input": c["input"], "ms": round((time.perf_counter() - t0) * 1000, 1),
                          **({"error": err} if err else {})})
            results.append({"type": "tool_result", "tool_use_id": c["id"], "content": content, **({"is_error": True} if err else {})})
        if submitted is not None:
            break
        messages.append({"role": "user", "content": results})

    seen = union.ids()
    cited = [c for c in dict.fromkeys((submitted or {}).get("citations") or []) if c in seen]
    if not submitted or not cited:
        return AskResult(None, ABSTAIN, True, [], Fragment(), [], trace, usage)

    beliefs = []
    for b in submitted.get("beliefs") or []:
        ev = [x for x in b.get("evidence") or [] if x in seen]
        if ev and b.get("text"):
            beliefs.append({"text": b["text"], "evidence": ev, "confidence": float(b.get("confidence", 0.5))})
    answer_id = await record_answer(agent_g, question, submitted.get("text", ""), cited, beliefs, as_of)
    if user_g is not None:
        areas = [r["id"] for r in await ro(company_g, Q.AREAS_OF_PEPS, {"ids": [c for c in cited if c.startswith("pep:")]})]
        await record_episode(user_g, question, answer_id, areas)
    return AskResult(answer_id, submitted.get("text", ""), False, cited, _evidence(union, cited), beliefs, trace, usage)
