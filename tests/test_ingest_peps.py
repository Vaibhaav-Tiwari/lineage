import json
from datetime import date
from pathlib import Path

from lineage.db import ro
from lineage.ingest.cache import fetch_cached
from lineage.ingest.peps import load_peps, parse_pep_date, parse_peps, parse_resolution
from lineage.schema import ensure_company_schema

RAW = json.loads((Path(__file__).parent / "fixtures" / "peps_sample.json").read_text())


def test_parse_pep_date():
    assert parse_pep_date("13-Jun-2000") == date(2000, 6, 13)
    assert parse_pep_date(None) is None


def test_parse_resolution_rst_link():
    assert parse_resolution("`08-May-2023 <https://discuss.python.org/t/pep-649-x/26803/1>`__") == (
        "https://discuss.python.org/t/pep-649-x/26803/1",
        date(2023, 5, 8),
    )


def test_parse_resolution_bare_url_and_empty():
    url = "https://mail.python.org/pipermail/python-dev/2017-December/151042.html"
    assert parse_resolution(url) == (url, None)
    assert parse_resolution("") == (None, None)
    assert parse_resolution(None) == (None, None)


def test_parse_peps_rows():
    rows = parse_peps(RAW)
    assert len(rows.peps) == 6
    assert [a["name"] for a in rows.authors if a["pep_id"] == "pep:100"] == ["Ann Author", "Bob Builder"]
    # superseded_by "102, 105" + replaces "101" describe overlapping edges: deduped
    assert sorted((s["src"], s["dst"]) for s in rows.supersedes) == [("pep:102", "pep:101"), ("pep:105", "pep:101")]
    assert rows.requires == [{"src": "pep:103", "dst": "pep:101"}]
    kinds = {(d["pep_id"], d["kind"]) for d in rows.decisions}
    assert kinds == {
        ("pep:100", "accept"), ("pep:101", "supersede"), ("pep:102", "accept"),
        ("pep:104", "reject"), ("pep:105", "accept"),
    }
    d100 = next(d for d in rows.decisions if d["id"] == "decision:pep:100:accept")
    assert d100["at"] == "2020-03-10"
    assert d100["source_url"] == "https://discuss.python.org/t/pep-100-sample/1000/2"


async def test_load_peps_builds_graph(g):
    await ensure_company_schema(g)
    await load_peps(g, parse_peps(RAW))
    assert await ro(g, "MATCH (:PEP {id:'pep:102'})-[:SUPERSEDES]->(:PEP {id:'pep:101'}) RETURN count(*) AS c") == [{"c": 1}]
    assert await ro(g, "MATCH (d:Decision)-[:DECIDES]->(:PEP {id:'pep:104'}) RETURN d.kind AS k") == [{"k": "reject"}]
    out = await ro(g, "MATCH (p:PEP {id:'pep:100'}) RETURN p.created.year AS y, p.status AS s, p.title AS t")
    assert out == [{"y": 2020, "s": "Accepted", "t": "Sample Accepted Feature"}]
    authors = await ro(g, "MATCH (a:Person)-[:AUTHORED]->(:PEP {id:'pep:100'}) RETURN a.name AS n ORDER BY n")
    assert [r["n"] for r in authors] == ["Ann Author", "Bob Builder"]


async def test_load_peps_is_idempotent(g):
    await ensure_company_schema(g)
    rows = parse_peps(RAW)
    await load_peps(g, rows)
    await load_peps(g, rows)
    counts = await ro(g, "MATCH (n) WITH count(n) AS n MATCH ()-[e]->() RETURN n, count(e) AS e")
    assert counts == [{"n": 6 + 5 + 5, "e": 7 + 2 + 1 + 5}]  # peps+people+decisions; authored+supersedes+requires+decides


async def test_fetch_cached_uses_cache_without_network(tmp_path):
    p = tmp_path / "x.json"
    p.write_bytes(b'{"ok": true}')
    assert await fetch_cached("http://example.invalid/never-called", p) == b'{"ok": true}'
