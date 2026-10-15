"""What a gated action actually does once the gate lets it through.

add_to_onboarding_faq  publishes the answer to the shared onboarding FAQ (lineage:shared);
                       the Steward withdraws it again if the evidence changes.
ask_owner_review       opens a task on the shared board for the people who own that part of Python.
"""

import time

from lineage.db import ro, rw
from lineage.graph import queries as Q

FAQ_KINDS = {"add_to_onboarding_faq", "add_to_faq"}


async def perform(kind: str, action_id: str, *, historian_g, shared_g, company_g) -> dict:
    rows = await ro(historian_g, Q.ACTION_ANSWER, {"id": action_id})
    ans = rows[0] if rows else None
    if kind in FAQ_KINDS and ans:
        fid = f"faq:{ans['id']}"
        await rw(shared_g, Q.PUBLISH_FAQ, {"id": fid, "answer_id": ans["id"], "question": ans["question"],
                                          "answer": ans["text"], "refs": ans["refs"], "now": time.time()})
        return {"kind": "faq", "faq": fid}
    if kind == "ask_owner_review" and ans:
        from lineage.memory.coord import open_fix_tasks

        peps = sorted(r for r in ans["refs"] if r.startswith("pep:"))
        target = peps[0] if peps else (ans["refs"] or [ans["id"]])[0]
        owners = {r["pep"]: r["owners"] for r in await ro(company_g, Q.AREA_OWNERS_OF_PEPS, {"ids": peps})} if peps else {}
        ids = await open_fix_tasks(shared_g, [{
            "kind": "owner-review", "target_ref": target, "suggested": sorted(owners.get(target, []))[:3],
            "reason": f"Please confirm the Historian's answer to “{ans['question']}” still holds; it rests on {', '.join(ans['refs'])}.",
        }])
        return {"kind": "task", "task": ids[0] if ids else None}
    return {"kind": "none"}


async def withdraw_faq(shared_g, answer_ids: list[str], reason: str, event: str) -> int:
    if not answer_ids:
        return 0
    rows = await rw(shared_g, Q.WITHDRAW_FAQ, {"answer_ids": answer_ids, "reason": reason, "event": event, "now": time.time()})
    return rows[0]["n"] if rows else 0


async def rely(company_g, agent_graphs: dict, ids: list[str]) -> list[dict]:
    """Can an agent still rely on these? Company facts and the Historian's own answers and beliefs."""
    out = {}
    for r in await ro(company_g, Q.RELY_COMPANY, {"ids": ids}):
        gone = r["status"] in ("Superseded", "Withdrawn", "Rejected") and r["label"] == "PEP"
        why = r["why"] or (f"status is {r['status']}" if gone else None)
        out[r["id"]] = {"id": r["id"], "reliable": not (r["stale"] or gone), "why": why, "replaced_by": sorted(r["replaced_by"])}
    for ag in agent_graphs.values():
        try:
            rows = await ro(ag, Q.RELY_AGENT, {"ids": [i for i in ids if i not in out]})
        except Exception:  # an agent that has not answered anything yet has no graph
            rows = []
        for r in rows:
            out[r["id"]] = {"id": r["id"], "reliable": not r["stale"], "why": r["why"], "replaced_by": []}
    return [out.get(i, {"id": i, "reliable": None, "why": "not in the graph", "replaced_by": []}) for i in ids]
