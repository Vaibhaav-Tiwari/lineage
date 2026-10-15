"""LLM backends that drive a ToolSession themselves.

- ClaudeCodeLLM: Claude through the local Claude Code login (Claude Agent SDK).
  For running on your own machine only — a public deployment must not use a
  personal subscription. Built-in tools are removed: Claude can only touch the
  graph, through an in-process MCP server.
- GraphOnlyLLM: no LLM at all. Finds the PEP, walks its decision path and
  writes the answer straight from the evidence. Used by the public deployment.
"""

import re

from lineage.config import settings

_PEP = re.compile(r"\bPEP[\s-]*(\d{1,4})\b", re.I)
_WHO = re.compile(r"\bwho\b.*\b(ask|work|working|maintain|maintains|owns|own|knows|expert|committing|active)", re.I)


def build_sdk_tools(session) -> list:
    from claude_agent_sdk import tool
    from lineage.graph.tools import TOOL_SPECS

    def make(spec):
        @tool(spec["name"], spec["description"], spec["input_schema"])
        async def handler(args):
            content, is_err = await session.call(spec["name"], args)
            return {"content": [{"type": "text", "text": content}], **({"is_error": True} if is_err else {})}

        return handler

    return [make(s) for s in TOOL_SPECS]


class ClaudeCodeLLM:
    def __init__(self, model: str | None = None, effort: str = "medium", max_turns: int = 14):
        self.model = model or settings().llm_model
        self.effort, self.max_turns = effort, max_turns

    def options(self, server, system: str = ""):
        from claude_agent_sdk import ClaudeAgentOptions

        return ClaudeAgentOptions(
            system_prompt=system,
            model=self.model,
            effort=self.effort,
            max_turns=self.max_turns,
            tools=[],                         # no file / shell / web tools at all
            mcp_servers={"lineage": server} if server else {},
            allowed_tools=["mcp__lineage__*"],
            setting_sources=[],               # ignore local CLAUDE.md, hooks, plugins
        )

    async def run_session(self, system: str, prompt: str, session, tool_specs) -> dict:
        from claude_agent_sdk import ResultMessage, create_sdk_mcp_server, query

        server = create_sdk_mcp_server(name="lineage", version="1.0.0", tools=build_sdk_tools(session))
        usage = {"backend": "claude-code"}
        try:
            async for msg in query(prompt=prompt + "\n\nRemember: finish by calling submit_answer.",
                                   options=self.options(server, system)):
                if isinstance(msg, ResultMessage):
                    u = msg.usage or {}
                    usage.update(input=u.get("input_tokens", 0), output=u.get("output_tokens", 0),
                                 cache_read=u.get("cache_read_input_tokens", 0), turns=msg.num_turns)
        except Exception as e:  # e.g. subscription usage limit: explain instead of crashing
            usage["error"] = str(e)
        return usage


class GraphOnlyLLM:
    """Deterministic: needs a PEP number or a module name in the question; otherwise it abstains."""

    async def _who(self, prompt: str, session) -> bool:
        from lineage.db import ro
        from lineage.graph import queries as Q

        if not _WHO.search(prompt):
            return False
        found = await ro(session.company_g, Q.AREAS_NAMED_IN, {"q": prompt})
        if not found:
            return False
        await session.call("who_knows", {"topic": found[0]["name"]})
        experts = session.union.meta.get("experts") or []
        if not experts:
            return False
        active = [e for e in experts if e.get("revealed")]
        listed = [e for e in experts if e.get("declared") and not e.get("revealed")]
        parts = []
        if active:
            parts.append("Actually committing in the last 12 months: " +
                         ", ".join(f"{e['name']} ({e.get('commits', 0)} commit{'' if e.get('commits') == 1 else 's'})" for e in active[:5]) + ".")
        if listed:
            parts.append("Listed as experts but not recently committing: " + ", ".join(e["name"] for e in listed[:5]) + ".")
        area = session.union.meta.get("area", {})
        session.submitted = {"text": f"For {area.get('name')}: " + " ".join(parts),
                             "citations": [e["id"] for e in active[:5] + listed[:5]], "beliefs": []}
        return True

    async def run_session(self, system: str, prompt: str, session, tool_specs) -> dict:
        question = prompt.rsplit("Question:", 1)[-1]
        if await self._who(question, session):
            return {"backend": "graph-only"}
        m = _PEP.search(question)
        if not m:
            return {"backend": "graph-only"}  # no PEP and no module named: abstain rather than guess
        pep = int(m.group(1))
        await session.call("decision_path", {"pep": pep})
        frag = session.union
        nodes = {n["id"]: n for n in frag.nodes}
        if f"pep:{pep}" not in nodes:
            return {"backend": "graph-only"}
        cited = [f"pep:{pep}"]
        lines = []
        for e in frag.edges:
            s, d = nodes.get(e["src"]), nodes.get(e["dst"])
            if not s or not d:
                continue
            if e["type"] == "DECIDES" and d["id"] == f"pep:{pep}":
                cited.append(s["id"])
                lines.append(f"Decision: {s['props'].get('kind')} ({s['props'].get('at') or 'date unknown'}).")
            elif e["type"] == "ANNOUNCED_BY":
                cited.append(d["id"])
                lines.append(f"Announced by {d['props'].get('name') or d['props'].get('github')}.")
            elif e["type"] == "SUPERSEDES":
                cited += [s["id"], d["id"]]
                lines.append(f"PEP {s['props'].get('number')} supersedes PEP {d['props'].get('number')}.")
            elif e["type"] == "AUTHORED" and d["id"] == f"pep:{pep}":
                cited.append(s["id"])
                lines.append(f"Author: {s['props'].get('name') or s['props'].get('github')}.")
        # the tool's summary line already resolves the status as of the requested date
        head = (frag.meta.get("summary") or "").split("\n")[0] or f"PEP {pep}"
        text = f"{head}. " + " ".join(dict.fromkeys(lines))
        session.submitted = {"text": text.strip(), "citations": list(dict.fromkeys(cited)), "beliefs": []}
        return {"backend": "graph-only"}


def make_llm(backend: str | None = None):
    backend = backend or settings().llm_backend
    if backend == "claude-code":
        return ClaudeCodeLLM()
    if backend == "graph-only":
        return GraphOnlyLLM()
    from lineage.agents.llm import AnthropicLLM

    return AnthropicLLM()
