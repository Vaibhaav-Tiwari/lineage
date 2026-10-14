"""peps.json → PEP, Person (authors), SUPERSEDES, REQUIRES, Decision."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from lineage import ids
from lineage.db import write_batch
from lineage.graph import queries as Q

PEPS_URL = "https://peps.python.org/api/peps.json"
_URL = re.compile(r"https?://[^\s<>`]+")
_DATE = re.compile(r"\b(\d{1,2}-[A-Z][a-z]{2}-\d{4})\b")


def parse_pep_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s.strip(), "%d-%b-%Y").date()


def parse_resolution(s: str | None) -> tuple[str | None, date | None]:
    """Handles bare URLs and RST links like ``08-May-2023 <https://...>`__``."""
    if not s:
        return None, None
    url = _URL.search(s)
    when = _DATE.search(s)
    return (url.group(0).rstrip(">") if url else None, parse_pep_date(when.group(1)) if when else None)


def _numbers(s: str | None) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", s or "")]


@dataclass
class PepRows:
    peps: list[dict] = field(default_factory=list)
    authors: list[dict] = field(default_factory=list)
    supersedes: list[dict] = field(default_factory=list)
    requires: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)


def _decisions(n: int, status: str, res_url: str | None, res_date: date | None) -> list[dict]:
    at = res_date.isoformat() if res_date else None
    out = []

    def add(kind, when=None):
        out.append({"id": ids.decision(n, kind), "pep_id": ids.pep(n), "kind": kind, "at": when, "source_url": res_url})

    if status in ("Accepted", "Final") or (status in ("Active", "Superseded", "Provisional") and res_url):
        add("accept", at)
    if status == "Rejected":
        add("reject", at)
    if status == "Superseded":
        add("supersede")  # date comes from replayable events, not peps.json
    if status == "Withdrawn":
        add("withdraw")
    if status == "Deferred":
        add("defer")
    return out


def parse_peps(raw: dict) -> PepRows:
    rows = PepRows()
    sup: set[tuple[str, str]] = set()
    for key, p in raw.items():
        n = int(p.get("number", key))
        res_url, res_date = parse_resolution(p.get("resolution"))
        created = parse_pep_date(p.get("created"))
        rows.peps.append({
            "id": ids.pep(n), "number": n, "title": p.get("title"), "status": p.get("status"),
            "type": p.get("type"), "topic": p.get("topic") or "", "python_version": p.get("python_version"),
            "url": p.get("url"), "created": created.isoformat() if created else None,
            "discussions_to": p.get("discussions_to"), "resolution_url": res_url,
        })
        for name in p.get("author_names") or [a.strip() for a in (p.get("authors") or "").split(",") if a.strip()]:
            rows.authors.append({"pep_id": ids.pep(n), "name": name})
        for newer in _numbers(p.get("superseded_by")):
            sup.add((ids.pep(newer), ids.pep(n)))
        for older in _numbers(p.get("replaces")):
            sup.add((ids.pep(n), ids.pep(older)))
        for req in _numbers(p.get("requires")):
            rows.requires.append({"src": ids.pep(n), "dst": ids.pep(req)})
        rows.decisions += _decisions(n, p.get("status") or "", res_url, res_date)
    rows.supersedes = [{"src": s, "dst": d} for s, d in sorted(sup)]
    return rows


def _default_person(name: str) -> str:
    return ids.person(ids.slug(name))


async def load_peps(g, rows: PepRows, person_id: Callable[[str], str] = _default_person) -> None:
    await write_batch(g, Q.UPSERT_PEPS, rows.peps)
    await write_batch(g, Q.UPSERT_AUTHORS, [{**a, "person_id": person_id(a["name"])} for a in rows.authors])
    await write_batch(g, Q.UPSERT_SUPERSEDES, rows.supersedes)
    await write_batch(g, Q.UPSERT_REQUIRES, rows.requires)
    await write_batch(g, Q.UPSERT_DECISIONS, rows.decisions)
