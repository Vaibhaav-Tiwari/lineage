"""Replayable real-world change events (config/events.yaml).

peps.json shows today's truth. For the demo we "rewind" an event (put the graph
back the way it was before), then the Steward applies it live and the change
ripples through every agent's memory.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from lineage import ids
from lineage.db import rw
from lineage.graph import queries as Q


@dataclass
class EventSpec:
    slug: str
    kind: str
    at: str
    pep: int
    before_status: str
    after_status: str
    by: list[int] = field(default_factory=list)
    summary: str = ""
    source_url: str = ""
    replay: bool = False


def load_events(path: Path) -> list[EventSpec]:
    data = yaml.safe_load(Path(path).read_text()) or []
    return [EventSpec(**{**d, "at": str(d["at"])}) for d in data]


_specs: dict[str, EventSpec] = {}


def _params(e: EventSpec) -> dict:
    return {
        "id": ids.event(e.slug), "pep_id": ids.pep(e.pep), "by": [ids.pep(b) for b in e.by],
        "decision_id": ids.decision(e.pep, "supersede"), "at": e.at,
        "summary": e.summary, "source_url": e.source_url,
    }


async def upsert_events(g, specs: list[EventSpec]) -> None:
    for e in specs:
        _specs[e.slug] = e
        p = _params(e)
        await rw(g, Q.UPSERT_EVENT, {**p, "kind": e.kind, "payload": json.dumps(asdict(e))})


async def _spec(g, slug: str) -> EventSpec:
    if slug in _specs:
        return _specs[slug]
    from lineage.db import ro

    rows = await ro(g, "MATCH (e:Event {id: $id}) RETURN e.payload_json AS p", {"id": ids.event(slug)})
    if not rows:
        raise KeyError(f"unknown event {slug}")
    e = EventSpec(**json.loads(rows[0]["p"]))
    _specs[slug] = e
    return e


async def rewind_event(g, slug: str) -> None:
    e = await _spec(g, slug)
    p = _params(e)
    await rw(g, Q.EVENT_SET_STATUS, {"pep_id": p["pep_id"], "status": e.before_status})
    if e.kind == "supersede":
        await rw(g, Q.EVENT_DELETE_SUPERSEDES, p)
        await rw(g, Q.EVENT_DELETE_DECISION, p)
    await rw(g, Q.EVENT_SET_APPLIED, {"id": p["id"], "applied": False})


async def mark_event_applied(g, slug: str) -> list[str]:
    e = await _spec(g, slug)
    p = _params(e)
    await rw(g, Q.EVENT_SET_STATUS, {"pep_id": p["pep_id"], "status": e.after_status})
    if e.kind == "supersede":
        await rw(g, Q.EVENT_ADD_SUPERSEDES, p)
        await rw(g, Q.EVENT_ADD_DECISION, p)
    await rw(g, Q.EVENT_SET_APPLIED, {"id": p["id"], "applied": True})
    return [p["pep_id"]]
