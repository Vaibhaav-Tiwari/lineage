"""The Historian: answers why / who / when questions about the company from
graph evidence only, cites stable ids, abstains when no evidence path exists,
and writes what it concluded into its own memory graph."""

import json
import time
from dataclasses import dataclass, field
from datetime import date

from lineage.db import ro
from lineage.graph import queries as Q
from lineage.graph.miss import explain_miss
from lineage.graph.search import hits_to_fragment, hybrid_search
from lineage.graph.subgraph import Fragment
from lineage.graph.tools import TOOL_SPECS, connection, decision_path, pep_timeline, related_peps, who_knows
from lineage.memory.store import record_answer, record_episode

MAX_TOOL_CALLS = 6

SYSTEM = """You are the Historian for the Python project's "company brain": a graph of PEPs (proposals), \
decisions, the people who wrote and decided them, forum discussions, implementing pull requests, and who \
owns which part of the code.

Answer only from what the tools return. Every claim in your answer must rest on ids that appeared in a tool \
result (e.g. pep:649, decision:pep:649:accept, person:gpshead, post:96520). For WHY / WHO DECIDED questions \
use decision_path; for WHEN, pep_timeline; for WHO SHOULD I ASK, who_knows; use search when you don't yet \
know which PEP is involved; for HOW IS X CONNECTED TO Y, connection. You have at most 6 tool calls.

Finish by calling submit_answer with a short, direct answer (2-6 sentences, name people and dates), the ids \
you rely on, and 1-3 beliefs you concluded with the ids each rests on and an honest confidence. If the tools \
do not contain the answer, submit an answer saying so with no citations - never guess.

Mark each claim in the text with footnote numbers that point into your citations list, 1-based, right after \
the sentence's punctuation: "PEP 649 was accepted on 2023-05-08.[1] Gregory P. Smith announced it.[2]" means \
citations[0] backs the first sentence and citations[1] the second. Every number must refer to a citation."""


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
    miss: dict | None = None  # why there is no answer, and what to try instead

    def to_json(self) -> dict:
        return {"answer_id": self.answer_id, "text": self.text, "abstained": self.abstained,
                "citations": self.citations, "evidence": self.evidence.to_json(), "beliefs": self.beliefs,
                "tool_trace": self.tool_trace, "usage": self.usage, "miss": self.miss}


async def _run_tool(name: str, inp: dict, company_g, embedder, as_of: date | None) -> Fragment:
    if name == "search":
        return hits_to_fragment(await hybrid_search(company_g, inp["query"], embedder, k=int(inp.get("k", 6)), as_of=as_of))
    if name == "decision_path":
        return await decision_path(company_g, int(inp["pep"]), as_of)
    if name == "pep_timeline":
        return await pep_timeline(company_g, int(inp["pep"]), as_of)
    if name == "who_knows":
        return await who_knows(company_g, str(inp["topic"]), as_of)
    if name == "connection":
        return await connection(company_g, str(inp["a"]), str(inp["b"]))
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


class ToolSession:
    """One question's tool use: runs graph tools, enforces the budget, records
    what was seen (for citation checks) and what was submitted. Every LLM
    backend drives the same session, so the rules are identical everywhere."""

    def __init__(self, company_g, embedder, as_of: date | None, max_calls: int = MAX_TOOL_CALLS):
        self.company_g, self.embedder, self.as_of, self.max_calls = company_g, embedder, as_of, max_calls
        self.union, self.trace, self.used, self.submitted = Fragment(), [], 0, None

    async def call(self, name: str, inp: dict) -> tuple[str, bool]:
        if name == "submit_answer":
            self.submitted = inp
            return "received", False
        if self.used >= self.max_calls:
            return "Tool budget used up. Call submit_answer now.", True
        self.used += 1
        t0 = time.perf_counter()
        found, summary = [], ""
        try:
            frag = await _run_tool(name, inp, self.company_g, self.embedder, self.as_of)
            self.union = self.union.merge(frag)
            content, err = json.dumps(frag.meta, default=str)[:12000], None
            found = [n["id"] for n in frag.nodes][:80]  # what this step reached, for "replay how this was found"
            summary = str(frag.meta.get("summary") or "").split("\n")[0][:160]
        except Exception as e:  # reported to the model, never crashes the request
            content, err = f"Error: {e}", str(e)
        self.trace.append({"name": name, "input": inp, "ms": round((time.perf_counter() - t0) * 1000, 1),
                           "found": found, "summary": summary, **({"error": err} if err else {})})
        return content, err is not None


async def _manual_loop(llm, prompt: str, session: ToolSession) -> dict:
    messages: list = [{"role": "user", "content": prompt}]
    usage, nudged = {"input": 0, "output": 0, "cache_read": 0}, False
    for _ in range(session.max_calls + 6):
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
            content, is_err = await session.call(c["name"], c["input"])
            results.append({"type": "tool_result", "tool_use_id": c["id"], "content": content, **({"is_error": True} if is_err else {})})
        if session.submitted is not None:
            break
        messages.append({"role": "user", "content": results})
    return usage


def _prompt(question: str, as_of: date | None, context: list[dict] | None, focus: str | None) -> str:
    """Follow-ups ("why was it decided this way?") need what's on screen: recent
    exchanges, Steward notes, and the item the user has open. The question goes last."""
    parts = []
    lines = []
    for c in (context or [])[-4:]:
        if c.get("note"):
            lines.append(f"- {c['note'][:500]}")
        elif c.get("q"):
            lines.append(f"- Earlier question: {c['q'][:300]}\n  Your answer: {(c.get('a') or '')[:600]}")
    if lines:
        parts.append("Conversation so far (use it to resolve words like 'it' or 'this'):\n" + "\n".join(lines))
    if focus:
        parts.append(f"The user currently has {focus} open.")
    if as_of:
        parts.append(f"Answer as of {as_of.isoformat()}: ignore anything that happened later.")
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)


def _normalise(question: str) -> str:
    """A question that is only a number ("455", "#455") means that PEP."""
    import re

    m = re.fullmatch(r"\s*#?\s*(\d{1,4})\s*\??\s*", question)
    return f"Tell me about PEP {int(m.group(1))}." if m else question


async def ask(question: str, *, company_g, agent_g, user_g, llm, embedder, as_of: date | None = None,
              context: list[dict] | None = None, focus: str | None = None) -> AskResult:
    question = _normalise(question)
    prompt = _prompt(question, as_of, context, focus)
    session = ToolSession(company_g, embedder, as_of)
    if hasattr(llm, "run_session"):  # backends that drive their own loop (Agent SDK, graph-only)
        usage = await llm.run_session(SYSTEM, prompt, session, TOOL_SPECS)
    else:
        usage = await _manual_loop(llm, prompt, session)
    return await _finish(question, session, company_g, agent_g, user_g, as_of, usage)


def _renumber(text: str, original: list[str], kept: list[str]) -> str:
    """Point footnote markers at the citations that survived; drop markers whose citation was dropped."""
    import re

    def sub(m: re.Match) -> str:
        i = int(m.group(1)) - 1
        ref = original[i] if 0 <= i < len(original) else None
        return f"[{kept.index(ref) + 1}]" if ref in kept else ""

    out = re.sub(r"\[(\d+)\]", sub, text)
    return re.sub(r"(\[\d+\])(?:\1)+", r"\1", out)  # [2][2] -> [2]


async def _finish(question, session: ToolSession, company_g, agent_g, user_g, as_of, usage) -> AskResult:
    submitted, seen = session.submitted, session.union.ids()
    cited = [c for c in dict.fromkeys((submitted or {}).get("citations") or []) if c in seen]
    if not submitted or not cited:
        miss = await explain_miss(company_g, question, as_of, usage.get("error"))
        return AskResult(None, miss["text"], True, [], Fragment(), [], session.trace, usage, miss)
    beliefs = []
    for b in submitted.get("beliefs") or []:
        ev = [x for x in b.get("evidence") or [] if x in seen]
        if ev and b.get("text"):
            beliefs.append({"text": b["text"], "evidence": ev, "confidence": float(b.get("confidence", 0.5))})
    original = list(dict.fromkeys((submitted or {}).get("citations") or []))
    submitted["text"] = _renumber(submitted.get("text", ""), original, cited)
    answer_id = await record_answer(agent_g, question, submitted.get("text", ""), cited, beliefs, as_of)
    if user_g is not None:
        areas = [r["id"] for r in await ro(company_g, Q.AREAS_OF_PEPS, {"ids": [c for c in cited if c.startswith("pep:")]})]
        await record_episode(user_g, question, answer_id, areas)
    return AskResult(answer_id, submitted.get("text", ""), False, cited, _evidence(session.union, cited),
                     beliefs, session.trace, usage)
