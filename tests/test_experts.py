from pathlib import Path

from lineage.db import ro
from lineage.ingest.experts import load_experts, parse_experts
from lineage.ingest.identity import IdentityResolver
from lineage.schema import ensure_company_schema

TEXT = (Path(__file__).parent / "fixtures" / "experts_sample.rst").read_text()


def _by(rows):
    return {(r["area"], r["github"]): r for r in rows}


def test_assignable_star_and_plain_names():
    rows = _by(parse_experts(TEXT))
    assert rows[("argparse", "alice")]["assignable"] is True
    assert rows[("argparse", "bob")]["assignable"] is False


def test_inactive_marker():
    r = _by(parse_experts(TEXT))[("xml", "carol")]
    assert r["inactive"] is True and r["github"] == "carol"


def test_continuation_rows_belong_to_previous_area():
    rows = _by(parse_experts(TEXT))
    assert ("zipfile", "frank") in rows and rows[("zipfile", "frank")]["assignable"] is True


def test_kinds_and_emeritus_ignored():
    rows = parse_experts(TEXT)
    kinds = {r["area"]: r["kind"] for r in rows}
    assert kinds["argparse"] == "module" and kinds["argument clinic"] == "tool" and kinds["packaging"] == "interest"
    assert not any(r["github"] == "oldtimer" for r in rows)


async def test_load_experts(g):
    await ensure_company_schema(g)
    await load_experts(g, parse_experts(TEXT), IdentityResolver({}))
    out = await ro(g, "MATCH (:Person {id:'person:alice'})-[e:EXPERT_IN]->(a:Area {id:'area:argparse'}) RETURN e.assignable AS x, a.kind AS k")
    assert out == [{"x": True, "k": "module"}]
    assert await ro(g, "MATCH (:Person)-[e:EXPERT_IN {inactive:true}]->(:Area {id:'area:xml'}) RETURN count(e) AS c") == [{"c": 1}]
