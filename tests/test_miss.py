"""Why there is no answer: worked out from the graph, with a next step to offer."""

from datetime import date

from lineage.db import rw
from lineage.graph.miss import explain_miss

SEED = """
CREATE (:PEP {id:'pep:301', number:301, title:'Package Index and Metadata for Distutils', status:'Final', created: date('2002-10-24'), pagerank: 0.2}),
       (:PEP {id:'pep:299', number:299, title:'Special __main__() function in modules', status:'Rejected', created: date('2002-08-12'), pagerank: 0.1}),
       (:PEP {id:'pep:8', number:8, title:'Style Guide for Python Code', status:'Active', created: date('2001-07-05'), pagerank: 0.9}),
       (:PEP {id:'pep:3156', number:3156, title:'Asynchronous IO Support Rebooted: the "asyncio" Module', status:'Final', created: date('2012-12-12'), pagerank: 0.5}),
       (:Area {id:'area:asyncio', name:'asyncio'})
"""


async def _seed(g):
    await rw(g, SEED)


async def test_a_pep_that_does_not_exist_names_the_nearest_ones(g):
    await _seed(g)
    m = await explain_miss(g, "Why was PEP 300 accepted?", as_of=None)
    assert m["kind"] == "missing"
    assert "no PEP 300" in m["text"] and "PEP 301" in m["text"] and "PEP 299" in m["text"]
    assert {"label": "Ask about PEP 301", "question": "Why was PEP 301 accepted?"} in m["actions"]


async def test_a_pep_written_after_the_dial_date_is_not_yet(g):
    await _seed(g)
    m = await explain_miss(g, "Who decided PEP 3156?", as_of=date(2001, 7, 14))
    assert m["kind"] == "not_yet"
    assert "2012-12-12" in m["text"] and "2001-07-14" in m["text"]
    assert {"label": "Ask as of today", "as_of": None} in m["actions"]
    assert {"label": "Move the dial to 2012-12-12", "as_of": "2012-12-12"} in m["actions"]


async def test_a_module_that_only_appears_later_is_not_yet(g):
    await _seed(g)
    m = await explain_miss(g, "Who should I ask about asyncio?", as_of=date(2001, 7, 14))
    assert m["kind"] == "not_yet"
    assert "asyncio" in m["text"] and "PEP 3156" in m["text"]


async def test_an_existing_pep_with_no_matching_record_is_unrecorded(g):
    await _seed(g)
    m = await explain_miss(g, "What did people eat while writing PEP 8?", as_of=None)
    assert m["kind"] == "unrecorded"
    assert "PEP 8" in m["text"] and "Style Guide" in m["text"]
    assert any(a.get("question") == "Why was PEP 8 decided this way?" for a in m["actions"])


async def test_nothing_recognised_suggests_a_question_that_fits_the_dial_date(g):
    await _seed(g)
    m = await explain_miss(g, "what's the weather", as_of=date(2001, 12, 31))
    assert m["kind"] == "unrecognised"
    assert {"label": "Try: Who decided PEP 8?", "question": "Who decided PEP 8?"} in m["actions"]


async def test_a_backend_failure_says_it_is_not_the_question(g):
    await _seed(g)
    m = await explain_miss(g, "Who decided PEP 8?", as_of=None, error="weekly limit reached")
    assert m["kind"] == "system"
    assert "weekly limit reached" in m["text"] and "not about your question" in m["text"]
    assert {"label": "Try again", "question": "Who decided PEP 8?"} in m["actions"]


async def test_ownership_before_the_snapshot_window_is_explained(g):
    await _seed(g)
    await rw(g, "CREATE (:PEP {id:'pep:3333', number:3333, title:'asyncio tweaks', status:'Final', created: date('2010-01-01')})")
    m = await explain_miss(g, "Who should I ask about asyncio?", as_of=date(2012, 1, 1))
    assert m["kind"] == "unrecorded"
    assert "2015" in m["text"] and "2012-01-01" in m["text"]
    assert {"label": "Ask as of today", "as_of": None} in m["actions"]
