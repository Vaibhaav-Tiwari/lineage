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
