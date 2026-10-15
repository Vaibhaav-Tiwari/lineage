from lineage.agents.historian import ask
from lineage.agents.llm import FakeLLM, LLMTurn
from lineage.db import ro, rw
from lineage.schema import ensure_agent_schema, ensure_company_schema, ensure_user_schema

from tests.test_tools import FIXTURE


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


def call(name, inp, i=0):
    return LLMTurn(text="", tool_calls=[{"id": f"t{i}", "name": name, "input": inp}], stop_reason="tool_use")


def submit(text, citations, beliefs=()):
    return call("submit_answer", {"text": text, "citations": citations, "beliefs": list(beliefs)}, 99)


async def _graphs(db):
    import uuid

    names = [f"test:{uuid.uuid4().hex[:8]}" for _ in range(3)]
    cg, ag, ug = (db.select_graph(n) for n in names)
    await ensure_company_schema(cg)
    await rw(cg, FIXTURE)
    await rw(cg, "MATCH (p:PEP {id:'pep:102'}) CREATE (p)-[:CONCERNS]->(:Area {id:'area:typing', name:'typing'})")
    await ensure_agent_schema(ag)
    await ensure_user_schema(ug)
    return cg, ag, ug


async def _cleanup(*gs):
    for g in gs:
        await g.delete()


async def test_happy_path_answer_with_valid_citations(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("decision_path", {"pep": 102}),
                       submit("PEP 102 was accepted; Bob announced it.", ["pep:102", "person:bob"],
                              [{"text": "Bob announced PEP 102's acceptance", "evidence": ["person:bob", "pep:102"], "confidence": 0.9}])])
        r = await ask("Who announced PEP 102?", company_g=cg, agent_g=ag, user_g=ug, llm=llm, embedder=FakeEmbedder())
        assert not r.abstained and r.citations == ["pep:102", "person:bob"]
        assert {"pep:102", "person:bob"} <= r.evidence.ids()
        assert await ro(ag, "MATCH (a:Answer) RETURN count(a) AS c") == [{"c": 1}]
        assert await ro(ug, "MATCH (:Episode)-[:SUGGESTS]->(i:Interest) RETURN i.area_ref AS a") == [{"a": "area:typing"}]
        assert r.tool_trace[0]["name"] == "decision_path" and r.tool_trace[0]["ms"] >= 0
    finally:
        await _cleanup(cg, ag, ug)


async def test_unseen_citations_are_dropped(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("decision_path", {"pep": 102}), submit("x", ["pep:102", "pep:9999"])])
        r = await ask("q", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert r.citations == ["pep:102"] and not r.abstained
    finally:
        await _cleanup(cg, ag, ug)


async def test_only_unseen_citations_means_abstain_and_nothing_stored(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("decision_path", {"pep": 102}), submit("made up", ["pep:9999"])])
        r = await ask("q", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert r.abstained and r.miss and r.text == r.miss["text"]
        assert r.answer_id is None
        assert await ro(ag, "MATCH (a:Answer) RETURN count(a) AS c") == [{"c": 0}]
    finally:
        await _cleanup(cg, ag, ug)


async def test_out_of_corpus_question_abstains(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("search", {"query": "Rust borrow checker lifetimes"}), submit("No idea.", [])])
        r = await ask("How does Rust's borrow checker work?", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert r.abstained
    finally:
        await _cleanup(cg, ag, ug)


async def test_tool_call_budget_is_enforced(db):
    cg, ag, ug = await _graphs(db)
    try:
        script = [call("related_peps", {"pep": 101}, i) for i in range(8)] + [submit("ok", ["pep:101"])]
        llm = FakeLLM(script)
        r = await ask("q", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert len(r.tool_trace) == 6
        assert not r.abstained and r.citations == ["pep:101"]
    finally:
        await _cleanup(cg, ag, ug)


async def test_ending_without_submit_gets_one_nudge_then_abstains(db):
    cg, ag, ug = await _graphs(db)
    try:
        done = LLMTurn(text="I think it was Bob.", tool_calls=[], stop_reason="end_turn")
        llm = FakeLLM([call("decision_path", {"pep": 102}), done, done])
        r = await ask("q", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert r.abstained and llm.calls == 3
    finally:
        await _cleanup(cg, ag, ug)


async def test_tool_errors_are_reported_not_raised(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("decision_path", {"pep": "not-a-number"}), call("decision_path", {"pep": 102}, 1), submit("ok", ["pep:102"])])
        r = await ask("q", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert not r.abstained
        assert r.tool_trace[0]["error"] and "error" not in r.tool_trace[1]
    finally:
        await _cleanup(cg, ag, ug)


async def test_follow_up_carries_conversation_and_focus(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([call("decision_path", {"pep": 102}), submit("Because Bob said so.", ["pep:102"])])
        ctx = [{"q": "Who announced PEP 102?", "a": "Bob announced it."}, {"note": "Steward: PEP 101 was superseded by PEP 102."}]
        await ask("why was it decided this way?", company_g=cg, agent_g=ag, user_g=None, llm=llm,
                  embedder=FakeEmbedder(), context=ctx, focus="pep:102")
        first_prompt = llm.first_prompt
        assert "Who announced PEP 102?" in first_prompt and "Bob announced it." in first_prompt
        assert "Steward: PEP 101 was superseded" in first_prompt
        assert "pep:102" in first_prompt and first_prompt.rstrip().endswith("why was it decided this way?")
    finally:
        await _cleanup(cg, ag, ug)


async def test_abstention_explains_what_to_try(db):
    cg, ag, ug = await _graphs(db)
    try:
        llm = FakeLLM([submit("No idea.", [])])
        r = await ask("why?", company_g=cg, agent_g=ag, user_g=None, llm=llm, embedder=FakeEmbedder())
        assert r.abstained and "PEP number" in r.text
    finally:
        await _cleanup(cg, ag, ug)


def test_footnotes_are_renumbered_when_an_unseen_citation_is_dropped():
    from lineage.agents.historian import _renumber

    text = "A happened.[1] B happened.[2] C happened.[3][2]"
    assert _renumber(text, ["pep:1", "bogus:x", "pep:3"], ["pep:1", "pep:3"]) == "A happened.[1] B happened. C happened.[2]"


def test_a_bare_number_is_read_as_a_pep_number():
    from lineage.agents.historian import _normalise

    assert _normalise("900") == "Tell me about PEP 900."
    assert _normalise(" #455? ") == "Tell me about PEP 455."
    assert _normalise("PEP 455") == "PEP 455"
    assert _normalise("what changed in 2020") == "what changed in 2020"
