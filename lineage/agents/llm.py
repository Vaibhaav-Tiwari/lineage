"""The model interface the agents use, so tests can run on a scripted FakeLLM."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from lineage.config import settings


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[dict]  # [{id, name, input}]
    stop_reason: str
    # the assistant content to append to history verbatim (thinking blocks included)
    assistant_content: Any = None
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    async def complete(self, system: str, messages: list, tools: list) -> LLMTurn: ...


class AnthropicLLM:
    """Claude via the official SDK. Adaptive thinking (Opus 5.5 default), explicit
    effort, automatic prompt caching of the stable system+tools prefix, and the
    server-side refusal fallback."""

    def __init__(self, model: str | None = None, effort: str = "medium"):
        import anthropic

        s = settings()
        self.model = model or s.llm_model
        self.effort = effort
        self.client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key) if s.anthropic_api_key else anthropic.AsyncAnthropic()

    async def complete(self, system: str, messages: list, tools: list) -> LLMTurn:
        r = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            cache_control={"type": "ephemeral"},
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": b.input} for b in r.content if b.type == "tool_use"]
        u = r.usage
        usage = {"input": u.input_tokens, "output": u.output_tokens,
                 "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}
        return LLMTurn(text=text, tool_calls=calls, stop_reason=r.stop_reason, assistant_content=r.content, usage=usage)


class FakeLLM:
    """Replays a scripted list of turns; records how it was called."""

    def __init__(self, turns: list[LLMTurn]):
        self.turns = list(turns)
        self.calls = 0
        self.last_tool_results: list[dict] = []

    async def complete(self, system: str, messages: list, tools: list) -> LLMTurn:
        self.calls += 1
        last = messages[-1]["content"] if messages else None
        if isinstance(last, list) and last and isinstance(last[0], dict) and last[0].get("type") == "tool_result":
            self.last_tool_results = last
        if not self.turns:
            return LLMTurn(text="", tool_calls=[], stop_reason="end_turn")
        t = self.turns.pop(0)
        if t.assistant_content is None:
            content = [{"type": "text", "text": t.text}] if t.text else []
            content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]} for c in t.tool_calls]
            t.assistant_content = content
        return t
