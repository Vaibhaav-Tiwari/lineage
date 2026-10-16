"""The Historian: answers why / who / when questions about the company from
graph evidence only, cites stable ids, abstains when no evidence path exists,
and writes what it concluded into its own memory graph."""

import asyncio
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
citations[0] backs the first sentence and citations[1] the second. Every number must refer to a citation. Cite the \
proposal's own id (e.g. pep:688) on the sentence that names it, alongside the people and decisions you cite. Refer to \
people by name, not by pronoun."""


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

    def __init__(self, company_g, embedder, as_of: date | None, max_calls: int = MAX_TOOL_CALLS, on_step=None):
        self.company_g, self.embedder, self.as_of, self.max_calls = company_g, embedder, as_of, max_calls
        self.union, self.trace, self.used, self.submitted = Fragment(), [], 0, None
        self.results: list[dict] = []  # what each tool returned, to hand a prefetch to the model
        self.on_step = on_step         # called with each trace entry as it happens (streaming)

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
        self.results.append({"name": name, "input": inp, "content": content})
        if self.on_step:
            self.on_step(self.trace[-1])
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


def _with_prefetch(prompt: str, results: list[dict]) -> str:
    """Hand the model the lookups already made, so it can answer in one turn. The question stays last."""
    done = "\n\n".join(f"{r['name']}({json.dumps(r['input'])}) returned:\n{r['content']}" for r in results)
    head, question = prompt.rsplit("Question:", 1)
    return (f"{head}Already looked up for you (these are tool results: cite their ids as usual):\n\n{done}\n\n"
            "If this answers the question, call submit_answer now without further tool calls. "
            f"Otherwise use the tools.\n\nQuestion:{question}")


async def ask_stream(question: str, *, company_g, agent_g, user_g, llm, embedder, as_of: date | None = None,
                     context: list[dict] | None = None, focus: str | None = None):
    """Yields {"type": "step", "step"} for each graph lookup as it happens, {"type": "draft", "result"} (an
    instant graph-only answer, not remembered) for backends that want a prefetch, then {"type": "final", "result"}.

    A prefetching backend (Claude) is slow per turn, so the obvious lookup is made for it first: the graph-only
    route (a named PEP's decision path, or a named module's owners), else a search for the question. If the model
    then fails without answering, the graph-only draft becomes the answer."""
    question = _normalise(question)
    prompt = _prompt(question, as_of, context, focus)
    queue: asyncio.Queue = asyncio.Queue()
    session = ToolSession(company_g, embedder, as_of, on_step=lambda s: queue.put_nowait({"type": "step", "step": s}))
    draft = None
    if getattr(llm, "prefetch", False):
        from lineage.agents.backends import GraphOnlyLLM

        await GraphOnlyLLM().run_session(SYSTEM, prompt, session, TOOL_SPECS)
        draft, session.submitted = session.submitted, None
        if not session.trace:
            await session.call("search", {"query": question})
        while not queue.empty():
            yield queue.get_nowait()
        if draft:
            text, cited, beliefs = _resolve(session, draft)
            if cited:
                yield {"type": "draft", "result": AskResult(None, text, False, cited, _evidence(session.union, cited),
                                                             beliefs, list(session.trace), {"backend": "graph-only"})}
            else:
                draft = None
        prompt = _with_prefetch(prompt, session.results)

    done = object()

    async def run() -> dict:
        try:
            if hasattr(llm, "run_session"):  # backends that drive their own loop (Agent SDK, graph-only)
                return await llm.run_session(SYSTEM, prompt, session, TOOL_SPECS)
            return await _manual_loop(llm, prompt, session)
        finally:
            queue.put_nowait(done)

    task = asyncio.create_task(run())
    while (item := await queue.get()) is not done:
        yield item
    usage = task.result()
    if session.submitted is None and draft:
        session.submitted, usage = draft, {**usage, "fallback": "graph-only"}
    yield {"type": "final", "result": await _finish(question, session, company_g, agent_g, user_g, as_of, usage)}


async def ask(question: str, *, company_g, agent_g, user_g, llm, embedder, as_of: date | None = None,
              context: list[dict] | None = None, focus: str | None = None) -> AskResult:
    async for e in ask_stream(question, company_g=company_g, agent_g=agent_g, user_g=user_g, llm=llm,
                              embedder=embedder, as_of=as_of, context=context, focus=focus):
        if e["type"] == "final":
            return e["result"]
    raise RuntimeError("ask_stream ended without a final answer")


def _renumber(text: str, original: list[str], kept: list[str]) -> str:
    """Point footnote markers at the citations that survived; drop markers whose citation was dropped."""
    import re

    def sub(m: re.Match) -> str:
        i = int(m.group(1)) - 1
        ref = original[i] if 0 <= i < len(original) else None
        return f"[{kept.index(ref) + 1}]" if ref in kept else ""

    out = re.sub(r"\[(\d+)\]", sub, text)
    return re.sub(r"(\[\d+\])(?:\1)+", r"\1", out)  # [2][2] -> [2]


def _resolve(session: ToolSession, submitted: dict) -> tuple[str, list[str], list[dict]]:
    """Keep only citations and belief evidence the tools actually returned; renumber the footnotes to match."""
    seen = session.union.ids()
    original = list(dict.fromkeys(submitted.get("citations") or []))
    cited = [c for c in original if c in seen]
    beliefs = []
    for b in submitted.get("beliefs") or []:
        ev = [x for x in b.get("evidence") or [] if x in seen]
        if ev and b.get("text"):
            beliefs.append({"text": b["text"], "evidence": ev, "confidence": float(b.get("confidence", 0.5))})
    return _renumber(submitted.get("text", ""), original, cited), cited, beliefs


async def _finish(question, session: ToolSession, company_g, agent_g, user_g, as_of, usage) -> AskResult:
    text, cited, beliefs = _resolve(session, session.submitted) if session.submitted else ("", [], [])
    if not cited:
        miss = await explain_miss(company_g, question, as_of, usage.get("error"))
        return AskResult(None, miss["text"], True, [], Fragment(), [], session.trace, usage, miss)
    answer_id = await record_answer(agent_g, question, text, cited, beliefs, as_of)
    if user_g is not None:
        areas = [r["id"] for r in await ro(company_g, Q.AREAS_OF_PEPS, {"ids": [c for c in cited if c.startswith("pep:")]})]
        await record_episode(user_g, question, answer_id, areas)
    return AskResult(answer_id, text, False, cited, _evidence(session.union, cited), beliefs, session.trace, usage)
