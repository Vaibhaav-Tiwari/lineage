"""Agent memory (Answer → Belief → Evidence) and per-user episodic memory."""

import json
import uuid
from datetime import date, datetime, timezone

from lineage.db import ro, rw
from lineage.graph import queries as Q
from lineage.graph.subgraph import Fragment

COMMIT_CONFIDENCE = 0.7


def _id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def record_answer(ag, question: str, text: str, cited_ids: list[str], beliefs: list[dict],
                        as_of: date | None) -> str:
    aid = _id("answer")
    now = _now()
    await rw(ag, Q.CREATE_ANSWER, {"id": aid, "question": question, "text": text, "now": now,
                                   "as_of": as_of.isoformat() if as_of else None})
    if cited_ids:
        await rw(ag, Q.LINK_EVIDENCE, {"src": aid, "refs": sorted(set(cited_ids))})
    rows = [{"id": _id("belief"), "text": b["text"], "confidence": float(b.get("confidence", 0)),
             "status": "committed" if float(b.get("confidence", 0)) >= COMMIT_CONFIDENCE else "tentative",
             "evidence": sorted(set(b.get("evidence") or []))} for b in beliefs]
    if rows:
        await rw(ag, Q.CREATE_BELIEFS, {"answer_id": aid, "beliefs": rows, "now": now})
        for r in rows:
            if r["evidence"]:
                await rw(ag, Q.LINK_EVIDENCE, {"src": r["id"], "refs": r["evidence"]})
    return aid


async def propose_action(ag, kind: str, payload: dict, derived_from: list[str]) -> str:
    xid = _id("action")
    await rw(ag, Q.CREATE_ACTION, {"id": xid, "kind": kind, "payload": json.dumps(payload),
                                   "derived_from": derived_from, "now": _now()})
    return xid


async def list_beliefs(ag, status: str | None = None) -> list[dict]:
    return await ro(ag, Q.LIST_BELIEFS, {"status": status})


async def record_episode(ug, question: str, answer_id: str, area_refs: list[str]) -> str:
    eid = _id("episode")
    await rw(ug, Q.CREATE_EPISODE, {"id": eid, "question": question, "answer_id": answer_id,
                                    "areas": sorted(set(area_refs)), "now": _now()})
    return eid


async def explain_interest(ug, area_ref: str) -> Fragment:
    rows = await ro(ug, Q.EXPLAIN_INTEREST, {"area": area_ref})
    f = Fragment(meta={"area": area_ref, "weight": rows[0]["w"] if rows else 0})
    if rows:
        f.nodes.append({"id": area_ref, "label": "Interest", "props": {"weight": rows[0]["w"]}})
    for r in rows:
        f.nodes.append({"id": r["eid"], "label": "Episode", "props": {"question": r["q"], "at": r["at"]}})
        f.edges.append({"src": r["eid"], "dst": area_ref, "type": "SUGGESTS", "props": {}})
    return f


async def forget_episode(ug, episode_id: str) -> None:
    await rw(ug, Q.FORGET_DECREMENT, {"id": episode_id})
    await rw(ug, Q.FORGET_EPISODE, {"id": episode_id})
    await rw(ug, Q.DROP_EMPTY_INTERESTS)


async def list_interests(ug) -> list[dict]:
    return await ro(ug, Q.LIST_INTERESTS)
