import json
import uuid
from pathlib import Path

import yaml

from lineage.agents.steward import apply_event, reset_event
from lineage.db import ro
from lineage.ingest.events import load_events, upsert_events
from lineage.ingest.peps import load_peps, parse_peps
from lineage.memory.store import propose_action, record_answer
from lineage.schema import ensure_agent_schema, ensure_company_schema

FIX = Path(__file__).parent / "fixtures"


async def test_apply_event_ripples_and_fans_out_to_every_agent(db, tmp_path):
    names = [f"test:{uuid.uuid4().hex[:8]}" for _ in range(3)]
    cg, a1, a2 = (db.select_graph(n) for n in names)
    try:
        await ensure_company_schema(cg)
        await load_peps(cg, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
        cfg = tmp_path / "e.yaml"
        cfg.write_text(yaml.safe_dump([{"slug": "pep-101-superseded", "kind": "supersede", "at": "2021-07-07", "pep": 101,
                                        "by": [102, 105], "before_status": "Final", "after_status": "Superseded",
                                        "summary": "101 replaced by 102", "replay": True}]))
        await upsert_events(cg, load_events(cfg))
        await reset_event(cg, [a1, a2], "pep-101-superseded")
        for ag in (a1, a2):
            await ensure_agent_schema(ag)
        ans = await record_answer(a1, "q", "a", ["pep:101"], [{"text": "x", "evidence": ["pep:101"], "confidence": 0.9}], None)
        act = await propose_action(a1, "add_to_faq", {}, [ans])
        await record_answer(a2, "q", "a", ["pep:104"], [], None)

        rep = await apply_event("pep-101-superseded", company_g=cg, agent_graphs={"historian": a1, "other": a2})
        assert rep["changed"] == ["pep:101"]
        assert "pep:103" in rep["ripple"]["soft"]  # 103 REQUIRES 101
        assert rep["agents"]["historian"]["actions_blocked"] == [act]
        assert rep["agents"]["other"] == {"beliefs": [], "answers": [], "actions_blocked": []}
        assert await ro(cg, "MATCH (p:PEP {id:'pep:101'}) RETURN p.status AS s, p.stale AS st") == [{"s": "Superseded", "st": True}]

        await reset_event(cg, [a1, a2], "pep-101-superseded")
        assert await ro(cg, "MATCH (n) WHERE n.stale = true RETURN count(n) AS c") == [{"c": 0}]
        assert await ro(cg, "MATCH (p:PEP {id:'pep:101'}) RETURN p.status AS s") == [{"s": "Final"}]
    finally:
        for g in (cg, a1, a2):
            await g.delete()
