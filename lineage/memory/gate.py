"""The action gate: an agent may only act on what it still has reason to believe."""

import uuid
from datetime import datetime, timezone

from lineage.db import ro, rw
from lineage.graph import queries as Q


class ActionBlocked(Exception):
    def __init__(self, reason: str, path: list[str]):
        super().__init__(reason)
        self.reason, self.path = reason, path


async def check_action(ag, action_id: str) -> dict:
    rows = await ro(ag, Q.GATE_ROOT_CAUSE_PATH, {"id": action_id}) or await ro(ag, Q.GATE_OFFENDING_PATH, {"id": action_id})
    if not rows:
        node = await ro(ag, Q.ACTION_NODE, {"id": action_id})
        if not node:
            return {"allowed": False, "reason": "unknown action", "path": []}
        return {"allowed": True, "reason": None, "path": []}
    r = rows[0]
    kind = "stale" if r["stale"] else "tentative"
    why = f" — {r['why'].rstrip('.')}" if r["why"] else ""  # the sentence below adds its own full stop
    reason = f"blocked: depends on {kind} {r['culprit']}{why}. Path: " + " ← ".join(r["path"])
    return {"allowed": False, "reason": reason, "path": r["path"]}


async def execute_action(ag, action_id: str) -> dict:
    """Runs a simulated action (writes an Outbox node; nothing external is sent)."""
    c = await check_action(ag, action_id)
    if not c["allowed"]:
        await rw(ag, Q.SET_ACTION_BLOCKED, {"id": action_id, "reason": c["reason"]})
        raise ActionBlocked(c["reason"], c["path"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = await rw(ag, Q.EXECUTE_ACTION, {"id": action_id, "oid": f"outbox:{uuid.uuid4().hex[:10]}", "now": now})
    return {"status": "done", "outbox": out[0]["id"]}
