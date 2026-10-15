from datetime import date

from lineage.db import rw
from lineage.graph.tools import TOOL_SPECS, decision_path, pep_timeline, related_peps, status_as_of, who_knows
from lineage.schema import ensure_company_schema

FIXTURE = """
CREATE (p101:PEP {id:'pep:101', number:101, title:'Old Way', status:'Superseded', created:date('2015-01-05')}),
       (p102:PEP {id:'pep:102', number:102, title:'New Way', status:'Final', created:date('2019-07-07')}),
       (p103:PEP {id:'pep:103', number:103, title:'Uses Old Way', status:'Active', created:date('2016-01-01')}),
       (bob:Person {id:'person:bob', name:'Bob'}), (dan:Person {id:'person:dan', name:'Dan'}),
       (alice:Person {id:'person:alice', github:'alice'}), (dave:Person {id:'person:dave', github:'dave'}),
       (area:Area {id:'area:argparse', name:'argparse'}),
       (d:Decision {id:'decision:pep:102:accept', kind:'accept', at:date('2019-09-01')}),
       (ds:Decision {id:'decision:pep:101:supersede', kind:'supersede', at:date('2020-05-01')}),
       (t:Thread {id:'thread:9', title:'PEP 102 discussion', created:date('2019-07-08')}),
       (po:Post {id:'post:90', post_number:7, created:date('2019-09-01')}),
       (pr:PR {id:'pr:1', title:'Implement PEP 102', merged_at:date('2019-10-01')}),
       (e:Event {id:'event:pep-101-superseded', at:date('2020-05-01'), kind:'supersede',
                 payload_json:'{"before_status": "Accepted", "after_status": "Superseded"}'}),
       (dan)-[:AUTHORED]->(p102), (d)-[:DECIDES]->(p102), (d)-[:RECORDED_IN]->(po), (d)-[:ANNOUNCED_BY]->(bob),
       (po)-[:IN]->(t), (p102)-[:DISCUSSED_IN]->(t), (p102)-[:SUPERSEDES]->(p101), (ds)-[:DECIDES]->(p101),
       (pr)-[:IMPLEMENTS]->(p102), (p103)-[:REFERENCES {count:2}]->(p101), (e)-[:AFFECTS]->(p101),
       (alice)-[:EXPERT_IN {assignable:true, inactive:false}]->(area),
       (dave)-[:COMMITTED_TO {count:4, last_at:date('2026-06-01')}]->(area)
"""


async def _setup(g):
    await ensure_company_schema(g)
    await rw(g, FIXTURE)


async def test_decision_path_collects_the_chain(g):
    await _setup(g)
    f = await decision_path(g, 102)
    assert {"pep:102", "pep:101", "decision:pep:102:accept", "person:bob", "pr:1", "person:dan"} <= f.ids()
    types = {e["type"] for e in f.edges}
    assert {"DECIDES", "ANNOUNCED_BY", "SUPERSEDES", "IMPLEMENTS", "AUTHORED"} <= types
    assert "embedding" not in str(f.nodes) and all("emb" not in n["props"] for n in f.nodes)
    assert "Bob" in f.meta["summary"]


async def test_decision_path_before_pep_existed_is_empty(g):
    await _setup(g)
    f = await decision_path(g, 102, as_of=date(1999, 1, 1))
    assert f.nodes == [] and f.edges == []


async def test_timeline_is_date_ordered_and_includes_event(g):
    await _setup(g)
    f = await pep_timeline(g, 101)
    when = [t["at"] for t in f.meta["timeline"]]
    assert when == sorted(when)
    assert any(t["kind"] == "event:supersede" for t in f.meta["timeline"])


def test_status_as_of():
    pep = {"status": "Superseded"}
    events = [{"at": date(2020, 5, 1), "before_status": "Accepted", "after_status": "Superseded"}]
    assert status_as_of(pep, events, date(2020, 1, 1)) == "Accepted"
    assert status_as_of(pep, events, date(2021, 1, 1)) == "Superseded"
    assert status_as_of(pep, events, None) == "Superseded"


async def test_who_knows_tags_declared_and_revealed(g):
    await _setup(g)
    f = await who_knows(g, "argparse")
    src = {x["id"]: x["source"] for x in f.meta["experts"]}
    assert src == {"person:alice": "declared", "person:dave": "revealed"}
    assert f.meta["experts"][0]["id"] == "person:dave"  # revealed recency first


async def test_who_knows_unknown_topic_is_empty_not_error(g):
    await _setup(g)
    f = await who_knows(g, "quantum-teleportation")
    assert f.meta["experts"] == [] and f.nodes == []


async def test_related_peps_hops_capped(g):
    await _setup(g)
    a = await related_peps(g, 101, hops=5)
    b = await related_peps(g, 101, hops=3)
    assert a.ids() == b.ids() and {"pep:102", "pep:103"} <= a.ids()


def test_tool_specs_cover_all_tools():
    names = {t["name"] for t in TOOL_SPECS}
    assert names == {"search", "decision_path", "pep_timeline", "who_knows", "related_peps", "connection", "submit_answer"}
    assert all("input_schema" in t and "description" in t for t in TOOL_SPECS)


async def test_unapplied_events_are_invisible_to_the_historian(g):
    await _setup(g)
    await rw(g, "MATCH (e:Event) SET e.applied = false")
    f = await pep_timeline(g, 101)
    assert not any(t["kind"].startswith("event:") for t in f.meta["timeline"])
    assert "event:pep-101-superseded" not in (await decision_path(g, 101)).ids()


async def test_who_knows_orders_by_commit_volume_then_recency(g):
    await _setup(g)
    await rw(g, """MATCH (a:Area {id:'area:argparse'})
                   CREATE (:Person {id:'person:big', github:'big'})-[:COMMITTED_TO {count:9, last_at:date('2026-01-01')}]->(a),
                          (:Person {id:'person:recent', github:'recent'})-[:COMMITTED_TO {count:1, last_at:date('2026-09-01')}]->(a)""")
    f = await who_knows(g, "argparse")
    assert [e["id"] for e in f.meta["experts"]][:3] == ["person:big", "person:dave", "person:recent"]


async def test_status_as_of_with_real_event_payload_shape(g):
    await _setup(g)
    await rw(g, """MATCH (e:Event) SET e.payload_json = '{"slug": "pep-101-superseded", "at": "2020-05-01", "before_status": "Accepted", "after_status": "Superseded", "pep": 101}'""")
    f = await decision_path(g, 101, as_of=date(2020, 1, 1))
    assert "status Accepted" in f.meta["summary"]


async def test_who_knows_refuses_dates_before_the_ownership_snapshot(g):
    from datetime import timedelta

    await _setup(g)
    old = await who_knows(g, "argparse", as_of=date(2001, 7, 14))
    assert old.meta["experts"] == [] and old.nodes == []
    assert "last 12 months" in old.meta["summary"]
    recent = await who_knows(g, "argparse", as_of=date.today() - timedelta(days=30))
    assert recent.meta["experts"]
