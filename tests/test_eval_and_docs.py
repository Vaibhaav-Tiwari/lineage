import re
import uuid
from pathlib import Path

from eval.run_eval import judge, render_markdown, run_eval
from lineage.agents.llm import FakeLLM, LLMTurn
from lineage.db import rw
from lineage.schema import ensure_company_schema
from scripts.gen_queries_doc import collect_queries

from tests.test_tools import FIXTURE


def test_judge_facts_citations_abstention():
    q = {"q": "x", "facts": [["Gregory P. Smith", "gpshead"], ["2023-05-08"]], "expected_ids": ["pep:649", "person:gpshead"]}
    r = judge(q, text="Gregory P. Smith announced it on 2023-05-08.", citations=["pep:649"], abstained=False)
    assert r["correct"] and r["citation_recall"] == 0.5 and r["missing"] == []
    r2 = judge(q, text="It was accepted.", citations=[], abstained=False)
    assert not r2["correct"] and r2["missing"] == ["Gregory P. Smith", "2023-05-08"]
    a = {"q": "y", "expect_abstain": True}
    assert judge(a, text="", citations=[], abstained=True)["correct"]
    assert not judge(a, text="Paris has 2M people", citations=[], abstained=False)["correct"]


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


async def test_run_eval_on_fixture_writes_rows_and_ripple(db, tmp_path):
    prefix = f"test{uuid.uuid4().hex[:6]}"
    cg = db.select_graph(f"{prefix}:company")
    try:
        await ensure_company_schema(cg)
        await rw(cg, FIXTURE)
        questions = {"questions": [
            {"q": "Who announced PEP 102?", "facts": [["Bob"]], "expected_ids": ["pep:102", "person:bob"]},
            {"q": "What is the population of Paris?", "expect_abstain": True},
        ]}
        scripts = iter([
            [LLMTurn("", [{"id": "a", "name": "decision_path", "input": {"pep": 102}}], "tool_use"),
             LLMTurn("", [{"id": "b", "name": "submit_answer", "input": {"text": "Bob did.", "citations": ["pep:102", "person:bob"], "beliefs": []}}], "tool_use")],
            [LLMTurn("", [{"id": "c", "name": "submit_answer", "input": {"text": "n/a", "citations": [], "beliefs": []}}], "tool_use")],
        ])
        res = await run_eval(db, prefix, questions, llm_factory=lambda: FakeLLM(next(scripts)), embedder=FakeEmbedder())
        assert res["summary"]["correct"] == 2 and res["summary"]["n"] == 2
        md = render_markdown(res, backend="fake")
        assert md.count("| Who announced PEP 102?") == 1 and "Ripple recall" in md
        assert f"{prefix}:agent:eval" not in await db.list_graphs()  # eval memory cleaned up
    finally:
        for n in await db.list_graphs():
            if n.startswith(prefix):
                await db.select_graph(n).delete()


def test_queries_doc_covers_every_constant():
    src = (Path(__file__).parents[1] / "lineage" / "graph" / "queries.py").read_text()
    names = set(re.findall(r"^([A-Z][A-Z0-9_]+) = ", src, re.M))
    docs = collect_queries()
    assert {d["name"] for d in docs} >= names - {"_TRIPLE", "_CARD", "_RIPPLE_SOFT"}
    assert all(d["cypher"].strip() for d in docs)
    assert any("serialises writes" in d["comment"] or "serialized" in d["comment"].lower() or "atomic" in d["comment"].lower() for d in docs)
