"""Graph tools the Historian calls. Each returns a Fragment: the subgraph it
looked at (for the evidence view) plus `meta` — a compact payload for the LLM."""

import json
from datetime import date

from lineage import ids
from lineage.db import ro
from lineage.graph import queries as Q
from lineage.graph.subgraph import Fragment

DATE_FIELDS = ("created", "at", "merged_at", "last_at")


def _clean(props: dict) -> dict:
    out = {}
    for k, v in (props or {}).items():
        if k == "emb":
            continue
        out[k] = v.isoformat() if isinstance(v, date) else v
    return out


def _when(props: dict):
    for f in DATE_FIELDS:
        v = props.get(f)
        if v:
            return date.fromisoformat(v) if isinstance(v, str) else v
    return None


def _fragment(rows: list[dict], as_of: date | None = None) -> Fragment:
    f = Fragment()
    seen = {}
    for r in rows:
        for nid, label, props in ((r["s"], r["sl"], r["sp"]), (r["d"], r["dl"], r["dp"])):
            if nid not in seen:
                seen[nid] = {"id": nid, "label": label, "props": _clean(props)}
        f.edges.append({"src": r["s"], "dst": r["d"], "type": r["t"], "props": _clean(r["rp"])})
    if as_of:
        late = {nid for nid, n in seen.items() if (w := _when(n["props"])) and w > as_of}
        seen = {k: v for k, v in seen.items() if k not in late}
        f.edges = [e for e in f.edges if e["src"] in seen and e["dst"] in seen]
    f.nodes = list(seen.values())
    return f.merge(Fragment())


def status_as_of(pep: dict, events: list[dict], as_of: date | None) -> str:
    """Status on a past date: the before-status of the earliest event after that date."""
    if as_of is None:
        return pep.get("status")
    later = sorted((e for e in events if e["at"] > as_of), key=lambda e: e["at"])
    return later[0]["before_status"] if later else pep.get("status")


async def _pep(g, n: int, as_of: date | None) -> dict | None:
    rows = await ro(g, Q.PEP_NODE, {"id": ids.pep(n)})
    if not rows:
        return None
    p = _clean(rows[0]["p"])
    if as_of and p.get("created") and date.fromisoformat(p["created"]) > as_of:
        return None
    return p


def _events(f: Fragment) -> list[dict]:
    out = []
    for n in f.nodes:
        if n["label"] == "Event" and n["props"].get("payload_json"):
            payload = json.loads(n["props"]["payload_json"])
            out.append({"at": date.fromisoformat(n["props"]["at"]), **payload})
    return out


def _name(n: dict) -> str:
    p = n["props"]
    return p.get("name") or p.get("github") or p.get("title") or n["id"]


async def decision_path(g, pep: int, as_of: date | None = None) -> Fragment:
    p = await _pep(g, pep, as_of)
    if not p:
        return Fragment(meta={"summary": f"PEP {pep} not found (or did not exist yet)."})
    pid = ids.pep(pep)
    rows = []
    for cypher in (Q.INTO_PEP, Q.DECISION_PROVENANCE, Q.SUPERSEDE_CHAIN, Q.PEP_THREADS):
        rows += await ro(g, cypher, {"id": pid})
    f = _fragment(rows, as_of)
    f.nodes.append({"id": pid, "label": "PEP", "props": p})
    f = f.merge(Fragment())
    by_id = {n["id"]: n for n in f.nodes}
    status = status_as_of(p, _events(f), as_of)
    lines = [f"PEP {pep}: {p.get('title')} — status {status}" + (f" (as of {as_of})" if as_of else "")]
    for e in f.edges:
        s, d = by_id.get(e["src"]), by_id.get(e["dst"])
        if not s or not d:
            continue
        if e["type"] == "AUTHORED":
            lines.append(f"- author: {_name(s)} [{s['id']}]")
        elif e["type"] == "DELEGATE_FOR":
            lines.append(f"- PEP-Delegate: {_name(s)} [{s['id']}]")
        elif e["type"] == "DECIDES":
            lines.append(f"- decision {s['props'].get('kind')} on {s['props'].get('at') or 'unknown date'} [{s['id']}]")
        elif e["type"] == "ANNOUNCED_BY":
            lines.append(f"- {s['id']} announced by {_name(d)} [{d['id']}]")
        elif e["type"] == "RECORDED_IN":
            lines.append(f"- {s['id']} recorded in {d['id']} {d['props'].get('source_url', '')}")
        elif e["type"] == "SUPERSEDES":
            lines.append(f"- {s['id']} supersedes {d['id']}")
        elif e["type"] == "IMPLEMENTS":
            lines.append(f"- implemented by {s['id']} '{s['props'].get('title')}'")
        elif e["type"] == "DISCUSSED_IN":
            lines.append(f"- discussed in {d['id']} '{d['props'].get('title')}'")
    f.meta = {"summary": "\n".join(lines), "pep": pid}
    return f


async def pep_timeline(g, pep: int, as_of: date | None = None) -> Fragment:
    f = await decision_path(g, pep, as_of)
    items = []
    for n in f.nodes:
        w = _when(n["props"])
        if not w:
            continue
        kind = {"PEP": "created", "Decision": f"decision:{n['props'].get('kind')}", "Post": "post",
                "PR": "pr-merged", "Thread": "thread-started", "Event": f"event:{n['props'].get('kind')}"}.get(n["label"], n["label"])
        items.append({"at": w.isoformat(), "kind": kind, "ref": n["id"]})
    f.meta = {**f.meta, "timeline": sorted(items, key=lambda x: x["at"])}
    return f


async def who_knows(g, topic: str, as_of: date | None = None) -> Fragment:
    found = await ro(g, Q.FIND_AREA, {"t": topic.strip()})
    if not found:
        return Fragment(meta={"experts": [], "summary": f"No area matching '{topic}'."})
    area = found[0]
    f = _fragment(await ro(g, Q.AREA_EXPERTS, {"id": area["id"]}), as_of)
    people: dict[str, dict] = {}
    for e in f.edges:
        n = next(x for x in f.nodes if x["id"] == e["src"])
        p = people.setdefault(n["id"], {"id": n["id"], "name": _name(n), "declared": False, "revealed": False})
        if e["type"] == "EXPERT_IN":
            p.update(declared=True, assignable=e["props"].get("assignable"), inactive=e["props"].get("inactive"))
        else:
            p.update(revealed=True, commits=e["props"].get("count"), last_at=e["props"].get("last_at"))
    for p in people.values():
        p["source"] = "both" if p["declared"] and p["revealed"] else "declared" if p["declared"] else "revealed"
    experts = list(people.values())
    experts.sort(key=lambda p: (p["revealed"], p.get("last_at") or ""), reverse=True)
    f.meta = {"area": area, "experts": experts,
              "summary": f"Area {area['name']}: " + "; ".join(f"{p['name']} ({p['source']})" for p in experts)}
    return f


async def related_peps(g, pep: int, hops: int = 2) -> Fragment:
    cypher = {1: Q.RELATED_1, 2: Q.RELATED_2}.get(max(1, min(hops, 3)), Q.RELATED_3)
    f = _fragment(await ro(g, cypher, {"id": ids.pep(pep)}))
    f.meta = {"summary": "\n".join(f"- {e['src']} {e['type']} {e['dst']}" for e in f.edges[:60])}
    return f


TOOL_SPECS = [
    {"name": "search", "description": "Find PEP text sections and forum posts relevant to a question (meaning + keywords). Use first when you don't know which PEP is involved.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 6}}, "required": ["query"]}},
    {"name": "decision_path", "description": "For one PEP: authors, delegate, every decision (kind, date), where it was announced and by whom, what it supersedes / is superseded by, implementing PRs, discussion threads. Best tool for WHY / WHO DECIDED questions.",
     "input_schema": {"type": "object", "properties": {"pep": {"type": "integer"}}, "required": ["pep"]}},
    {"name": "pep_timeline", "description": "Dated events for one PEP in order: created, decisions, posts, PRs merged, supersede events. Best tool for WHEN questions.",
     "input_schema": {"type": "object", "properties": {"pep": {"type": "integer"}}, "required": ["pep"]}},
    {"name": "who_knows", "description": "People for a Python area/module (e.g. 'asyncio', 'typing'): listed experts (declared) and people actually committing in the last 12 months (revealed). Best tool for WHO SHOULD I ASK questions.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "related_peps", "description": "PEPs connected to one PEP by references, supersedes or requires links (1-3 hops).",
     "input_schema": {"type": "object", "properties": {"pep": {"type": "integer"}, "hops": {"type": "integer", "default": 2}}, "required": ["pep"]}},
    {"name": "submit_answer", "description": "Finish. Give the answer text, the ids you cite (ONLY ids that appeared in tool results, e.g. 'pep:649', 'person:gpshead', 'decision:pep:649:accept'), and 1-3 short beliefs you concluded, each with the ids it rests on and a confidence 0-1.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "citations": {"type": "array", "items": {"type": "string"}},
         "beliefs": {"type": "array", "items": {"type": "object", "properties": {
             "text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}, "confidence": {"type": "number"}},
             "required": ["text", "evidence", "confidence"]}}},
         "required": ["text", "citations", "beliefs"]}},
]
