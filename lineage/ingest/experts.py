"""devguide core-team/experts.rst → Area nodes + declared EXPERT_IN edges.

The file holds RST "simple tables": a rule line of ===  === marks the column
boundary; a row whose first column is blank continues the previous row.
"""

import re

from lineage import ids
from lineage.db import write_batch
from lineage.graph import queries as Q

EXPERTS_URL = "https://raw.githubusercontent.com/python/devguide/main/core-team/experts.rst"
_KINDS = {"stdlib": "module", "tools": "tool", "miscellaneous": "interest"}
_RULE = re.compile(r"^(=+)(\s+)=+\s*$")
_TITLE_RULE = re.compile(r"^[=\-~^]{3,}\s*$")


def _names(cell: str):
    for raw in cell.split(","):
        raw = raw.strip()
        if not raw:
            continue
        inactive = "(inactive)" in raw
        name = raw.replace("(inactive)", "").strip()
        yield name.rstrip("*"), name.endswith("*"), inactive


def parse_experts(text: str) -> list[dict]:
    lines = text.splitlines()
    rows, section, i = [], None, 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and _TITLE_RULE.match(nxt) and not _RULE.match(line):
            title = line.strip().lower()
            if title == "experts emeritus":
                break
            section = _KINDS.get(title, section if title not in ("platforms",) else None)
            i += 2
            continue
        m = _RULE.match(line)
        if m and section:
            col = len(m.group(1)) + len(m.group(2))
            i += 3  # rule, header row, rule
            area = None
            while i < len(lines) and not _RULE.match(lines[i]):
                row = lines[i]
                if row.strip():
                    left, right = row[:col].strip(), row[col:]
                    area = left.lower() if left else area
                    for gh, star, inactive in _names(right):
                        rows.append({"area": area, "kind": section, "github": gh, "assignable": star, "inactive": inactive})
                i += 1
        i += 1
    return rows


async def load_experts(g, rows: list[dict], resolver) -> None:
    out = [
        {**r, "area_id": ids.area(r["area"]), "person_id": resolver.resolve(github=r["github"])}
        for r in rows
    ]
    await write_batch(g, Q.UPSERT_EXPERTS, out)
