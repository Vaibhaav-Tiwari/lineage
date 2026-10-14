import json
from pathlib import Path

import yaml

from lineage.db import ro
from lineage.ingest.events import load_events, mark_event_applied, rewind_event, upsert_events
from lineage.ingest.peps import load_peps, parse_peps
from lineage.schema import ensure_company_schema

FIX = Path(__file__).parent / "fixtures"


async def _setup(g, tmp_path):
    await ensure_company_schema(g)
    await load_peps(g, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
    cfg = tmp_path / "events.yaml"
    cfg.write_text(yaml.safe_dump([{
        "slug": "pep-101-superseded", "kind": "supersede", "at": "2021-07-07", "pep": 101, "by": [102, 105],
        "before_status": "Final", "after_status": "Superseded", "summary": "101 replaced", "source_url": "https://x", "replay": True,
    }]))
    specs = load_events(cfg)
    await upsert_events(g, specs)
    return specs


async def test_rewind_then_apply_restores_state(g, tmp_path):
    await _setup(g, tmp_path)
    await rewind_event(g, "pep-101-superseded")
    assert await ro(g, "MATCH (p:PEP {id:'pep:101'}) RETURN p.status AS s") == [{"s": "Final"}]
    assert await ro(g, "MATCH ()-[r:SUPERSEDES]->(:PEP {id:'pep:101'}) RETURN count(r) AS c") == [{"c": 0}]
    assert await ro(g, "MATCH (d:Decision {id:'decision:pep:101:supersede'}) RETURN count(d) AS c") == [{"c": 0}]
    assert await ro(g, "MATCH (e:Event {id:'event:pep-101-superseded'}) RETURN e.applied AS a") == [{"a": False}]

    changed = await mark_event_applied(g, "pep-101-superseded")
    assert changed == ["pep:101"]
    assert await ro(g, "MATCH (p:PEP {id:'pep:101'}) RETURN p.status AS s") == [{"s": "Superseded"}]
    assert await ro(g, "MATCH (n)-[:SUPERSEDES]->(:PEP {id:'pep:101'}) RETURN n.id AS id ORDER BY id") == [{"id": "pep:102"}, {"id": "pep:105"}]
    out = await ro(g, "MATCH (d:Decision {id:'decision:pep:101:supersede'})-[:DECIDES]->(:PEP {id:'pep:101'}) RETURN toString(d.at) AS at")
    assert out == [{"at": "2021-07-07"}]
    assert await ro(g, "MATCH (e:Event {id:'event:pep-101-superseded'})-[:AFFECTS]->(p:PEP) RETURN e.applied AS a, p.id AS p") == [{"a": True, "p": "pep:101"}]


async def test_apply_twice_is_idempotent(g, tmp_path):
    await _setup(g, tmp_path)
    await mark_event_applied(g, "pep-101-superseded")
    await mark_event_applied(g, "pep-101-superseded")
    assert await ro(g, "MATCH ()-[r:SUPERSEDES]->(:PEP {id:'pep:101'}) RETURN count(r) AS c") == [{"c": 2}]
