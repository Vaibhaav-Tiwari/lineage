from lineage.agents.backends import ClaudeCodeLLM, GraphOnlyLLM, build_sdk_tools
from lineage.agents.historian import ToolSession, ask
from lineage.db import ro

from tests.test_historian import FakeEmbedder, _cleanup, _graphs


async def test_graph_only_answers_from_decision_path(db):
    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("Who announced the acceptance of PEP 102?", company_g=cg, agent_g=ag, user_g=None,
                      llm=GraphOnlyLLM(), embedder=FakeEmbedder())
        assert not r.abstained
        assert {"pep:102", "person:bob"} <= set(r.citations)
        assert "Bob" in r.text
        assert await ro(ag, "MATCH (a:Answer) RETURN count(a) AS c") == [{"c": 1}]
    finally:
        await _cleanup(cg, ag, ug)


async def test_graph_only_abstains_without_a_pep(db):
    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("What is the airspeed of a swallow?", company_g=cg, agent_g=ag, user_g=None,
                      llm=GraphOnlyLLM(), embedder=FakeEmbedder())
        assert r.abstained
    finally:
        await _cleanup(cg, ag, ug)


async def test_sdk_tool_handlers_route_through_the_session(db):
    cg, ag, ug = await _graphs(db)
    try:
        s = ToolSession(cg, FakeEmbedder(), None)
        tools = {t.name: t for t in build_sdk_tools(s)}
        assert set(tools) == {"search", "decision_path", "pep_timeline", "who_knows", "related_peps", "submit_answer"}
        out = await tools["decision_path"].handler({"pep": 102})
        assert "Bob" in out["content"][0]["text"] and not out.get("is_error")
        await tools["submit_answer"].handler({"text": "t", "citations": ["pep:102"], "beliefs": []})
        assert s.submitted["citations"] == ["pep:102"]
        assert len(s.trace) == 1
    finally:
        await _cleanup(cg, ag, ug)


def test_claude_code_backend_uses_no_builtin_tools():
    opts = ClaudeCodeLLM().options(server=None)
    assert opts.tools == [] and opts.setting_sources == []
    assert opts.allowed_tools == ["mcp__lineage__*"]


async def test_claude_code_errors_become_an_explained_abstention(db, monkeypatch):
    import claude_agent_sdk

    async def boom(*a, **k):
        raise RuntimeError("You've hit your weekly limit")
        yield  # pragma: no cover

    monkeypatch.setattr(claude_agent_sdk, "query", boom)
    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("Who announced PEP 102?", company_g=cg, agent_g=ag, user_g=None, llm=ClaudeCodeLLM(), embedder=FakeEmbedder())
        assert r.abstained and "weekly limit" in r.usage["error"]
        assert "LLM unavailable" in r.text
    finally:
        await _cleanup(cg, ag, ug)


async def test_graph_only_routes_who_questions_to_who_knows(db):
    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("Who should I ask about argparse these days?", company_g=cg, agent_g=ag, user_g=None,
                      llm=GraphOnlyLLM(), embedder=FakeEmbedder())
        assert not r.abstained and "dave" in r.text and "person:dave" in r.citations
        assert r.tool_trace[0]["name"] == "who_knows"
    finally:
        await _cleanup(cg, ag, ug)


async def test_graph_only_without_pep_or_module_abstains(db):
    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("How does Rust's borrow checker handle lifetimes?", company_g=cg, agent_g=ag, user_g=None,
                      llm=GraphOnlyLLM(), embedder=FakeEmbedder())
        assert r.abstained and r.tool_trace == []
    finally:
        await _cleanup(cg, ag, ug)


async def test_graph_only_reports_status_as_of_the_requested_date(db):
    from datetime import date

    cg, ag, ug = await _graphs(db)
    try:
        r = await ask("What was the status of PEP 101 back then?", company_g=cg, agent_g=ag, user_g=None,
                      llm=GraphOnlyLLM(), embedder=FakeEmbedder(), as_of=date(2020, 1, 1))
        assert "Accepted" in r.text and "Superseded" not in r.text.split(".")[0]
    finally:
        await _cleanup(cg, ag, ug)
