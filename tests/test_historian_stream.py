"""Streaming answers: live steps, an instant graph-only draft, and evidence handed to the model up front."""

import json

from lineage.agents.backends import GraphOnlyLLM
from lineage.agents.historian import ask, ask_stream
from lineage.db import ro

from tests.test_api import app_env  # noqa: F401  (fixture)
from tests.test_historian import FakeEmbedder, _cleanup, _graphs


class PrefetchingLLM:
    """Stands in for Claude: drives its own loop, wants evidence gathered before it starts."""

    prefetch = True

    def __init__(self, submit=None, usage=None):
        self.submit, self.usage, self.prompt = submit, usage or {"backend": "fake"}, None

    async def run_session(self, system, prompt, session, tool_specs):
        self.prompt = prompt
        if self.submit:
            await session.call("submit_answer", self.submit)
        return dict(self.usage)


async def _events(question, cg, ag, llm, **kw):
    return [e async for e in ask_stream(question, company_g=cg, agent_g=ag, user_g=None, llm=llm,
                                        embedder=FakeEmbedder(), **kw)]


async def test_graph_only_streams_its_steps_then_the_final_answer(db):
    cg, ag, ug = await _graphs(db)
    try:
        ev = await _events("Who announced the acceptance of PEP 102?", cg, ag, GraphOnlyLLM())
        assert [e["type"] for e in ev] == ["step", "final"]
        assert ev[0]["step"]["name"] == "decision_path" and "pep:102" in ev[0]["step"]["found"]
        assert ev[-1]["result"].answer_id and not ev[-1]["result"].abstained
    finally:
        await _cleanup(cg, ag, ug)


async def test_a_prefetching_model_gets_an_unsaved_draft_first_and_the_evidence_in_its_prompt(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = PrefetchingLLM(submit={"text": "Bob announced PEP 102's acceptance.[1]",
                                     "citations": ["person:bob", "pep:102"], "beliefs": []})
        ev = await _events("Who announced the acceptance of PEP 102?", cg, ag, llm)
        assert [e["type"] for e in ev] == ["step", "draft", "final"]
        draft, final = ev[1]["result"], ev[2]["result"]
        assert draft.answer_id is None and "Bob" in draft.text and "pep:102" in draft.citations
        assert {"pep:102", "person:bob"} <= draft.evidence.ids()
        assert final.answer_id and final.text.startswith("Bob announced")
        # the model was handed the lookup instead of having to make it
        assert "decision_path" in llm.prompt and "person:bob" in llm.prompt
        assert llm.prompt.rstrip().endswith("Question: Who announced the acceptance of PEP 102?")
        # only the final answer is remembered
        assert await ro(ag, "MATCH (a:Answer) RETURN count(a) AS c") == [{"c": 1}]
    finally:
        await _cleanup(cg, ag, ug)


async def test_when_the_model_fails_the_draft_becomes_the_answer(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = PrefetchingLLM(submit=None, usage={"backend": "fake", "error": "usage limit reached"})
        ev = await _events("Who announced the acceptance of PEP 102?", cg, ag, llm)
        final = ev[-1]["result"]
        assert not final.abstained and final.answer_id and "Bob" in final.text
        assert final.usage["fallback"] == "graph-only" and final.usage["error"] == "usage limit reached"
        assert await ro(ag, "MATCH (a:Answer) RETURN count(a) AS c") == [{"c": 1}]
    finally:
        await _cleanup(cg, ag, ug)


async def test_without_a_pep_or_module_the_prefetch_is_a_search_and_there_is_no_draft(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = PrefetchingLLM(submit=None)
        ev = await _events("Why do people argue about the old way?", cg, ag, llm)
        assert "draft" not in [e["type"] for e in ev]
        assert ev[0]["type"] == "step" and ev[0]["step"]["name"] == "search"
        assert "search" in llm.prompt and ev[-1]["result"].abstained
    finally:
        await _cleanup(cg, ag, ug)


async def test_ask_returns_the_streamed_final_answer(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = PrefetchingLLM(submit={"text": "Bob announced it.[1]", "citations": ["person:bob"], "beliefs": []})
        r = await ask("Who announced the acceptance of PEP 102?", company_g=cg, agent_g=ag, user_g=None,
                      llm=llm, embedder=FakeEmbedder())
        assert r.answer_id and r.text == "Bob announced it.[1]" and r.citations == ["person:bob"]
    finally:
        await _cleanup(cg, ag, ug)


async def test_ask_stream_endpoint_sends_one_json_event_per_line(app_env):  # noqa: F811
    c, _, _ = app_env
    r = await c.post("/ask/stream", json={"question": "Who announced PEP 102?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    ev = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert [e["type"] for e in ev] == ["step", "final"]
    assert ev[-1]["result"]["citations"] == ["pep:102", "person:bob"] and ev[-1]["result"]["answer_id"]
