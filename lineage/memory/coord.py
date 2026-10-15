"""FixTask board in lineage:shared — the agents' shared to-do list."""

import time

from lineage.db import ro, rw
from lineage.graph import queries as Q


def _task_id(kind: str, target: str) -> str:
    return f"fix:{kind}:{target}"


async def open_fix_tasks(sg, items: list[dict]) -> list[str]:
    rows = [{"id": _task_id(i["kind"], i["target_ref"]), "kind": i["kind"], "target_ref": i["target_ref"],
             "reason": i["reason"], "suggested": i.get("suggested") or []} for i in items]
    if not rows:
        return []
    return [r["id"] for r in await rw(sg, Q.UPSERT_FIX_TASKS, {"rows": rows, "now": time.time()})]


async def claim_next(sg, agent: str, ttl_s: int = 300) -> dict | None:
    now = time.time()
    rows = await rw(sg, Q.CLAIM_NEXT, {"agent": agent, "now": now, "until": now + ttl_s})
    return rows[0] if rows else None


async def complete(sg, task_id: str, agent: str) -> None:
    if not await rw(sg, Q.COMPLETE_TASK, {"id": task_id, "agent": agent, "now": time.time()}):
        raise PermissionError(f"{agent} does not hold {task_id}")


async def list_tasks(sg, status: str | None = None) -> list[dict]:
    return await ro(sg, Q.LIST_TASKS, {"status": status})


async def open_fix_tasks_for(sg, company_g, ripple: dict, reason: str) -> list[str]:
    soft = ripple.get("soft") or []
    if not soft:
        return []
    owners = {r["pep"]: r["owners"][:3] for r in await ro(company_g, Q.AREA_OWNERS_OF_PEPS, {"ids": soft})}
    changed = ", ".join(ripple["hard"])
    items = [{"kind": "review-citation", "target_ref": pep, "suggested": sorted(owners.get(pep, [])),
              "reason": f"{pep} cites {changed}, which changed: {reason}"} for pep in soft]
    return await open_fix_tasks(sg, items)
