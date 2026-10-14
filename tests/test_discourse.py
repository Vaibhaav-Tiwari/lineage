import json
from pathlib import Path

from lineage.db import ro
from lineage.ingest.discourse import html_to_text, link_decision_provenance, load_topic, parse_discuss_url, parse_topic
from lineage.ingest.identity import IdentityResolver
from lineage.ingest.peps import load_peps, parse_peps
from lineage.schema import ensure_company_schema

FIX = Path(__file__).parent / "fixtures"
TOPIC = json.loads((FIX / "discourse_topic_sample.json").read_text())


class FakeEmbedder:
    def embed(self, texts):
        return [[0.2] * 384 for _ in texts]


def test_parse_discuss_url_forms():
    assert parse_discuss_url("https://discuss.python.org/t/pep-695-type-parameter-syntax/19999/42") == (19999, 42)
    assert parse_discuss_url("https://discuss.python.org/t/pep-695-type-parameter-syntax/19999") == (19999, None)
    assert parse_discuss_url("https://discuss.python.org/t/19999") == (19999, None)
    assert parse_discuss_url("https://discuss.python.org/t/19999/7") == (19999, 7)
    assert parse_discuss_url("https://mail.python.org/archives/list/python-dev@python.org/thread/X/") is None
    assert parse_discuss_url(None) is None


def test_html_to_text():
    assert html_to_text("<p>We <b>accept</b> PEP 1</p>") == "We accept PEP 1"
    assert html_to_text("<p>a &amp; b</p>\n<p>c</p>") == "a & b\nc"


def test_parse_topic():
    rows = parse_topic(TOPIC)
    assert rows.thread["id"] == "thread:3000" and rows.thread["title"] == "PEP 100: Sample feature"
    assert [p["post_number"] for p in rows.posts] == [1, 2, 3]
    assert rows.posts[1]["url"] == "https://discuss.python.org/t/pep-100-sample/3000/2"


async def _setup(g):
    await ensure_company_schema(g)
    await load_peps(g, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
    rows = parse_topic(TOPIC)
    await load_topic(g, rows, IdentityResolver({}), FakeEmbedder(), pep_ids=["pep:100"])
    return rows


async def test_load_topic(g):
    await _setup(g)
    assert await ro(g, "MATCH (:Person)-[:POSTED]->(p:Post)-[:IN]->(:Thread {id:'thread:3000'}) RETURN count(p) AS c") == [{"c": 3}]
    assert await ro(g, "MATCH (:PEP {id:'pep:100'})-[:DISCUSSED_IN]->(t:Thread) RETURN t.id AS id") == [{"id": "thread:3000"}]


async def test_decision_provenance_with_post_number(g):
    rows = await _setup(g)
    await link_decision_provenance(g, 100, "https://discuss.python.org/t/pep-100-sample/3000/2", rows)
    out = await ro(g, """MATCH (d:Decision {id:'decision:pep:100:accept'})-[:RECORDED_IN]->(po:Post),
                          (d)-[:ANNOUNCED_BY]->(a:Person) RETURN po.post_number AS n, a.name AS who, toString(d.at) AS at""")
    assert out == [{"n": 2, "who": "Steering Person", "at": "2020-03-10"}]


async def test_decision_provenance_without_post_number_links_thread(g):
    rows = await _setup(g)
    await link_decision_provenance(g, 100, "https://discuss.python.org/t/pep-100-sample/3000", rows)
    out = await ro(g, "MATCH (:Decision {id:'decision:pep:100:accept'})-[:RECORDED_IN]->(t:Thread) RETURN t.id AS id")
    assert out == [{"id": "thread:3000"}]
    assert await ro(g, "MATCH (:Decision {id:'decision:pep:100:accept'})-[:ANNOUNCED_BY]->() RETURN count(*) AS c") == [{"c": 0}]
