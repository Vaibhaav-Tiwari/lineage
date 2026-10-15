"""Generate docs/queries.md from lineage/graph/queries.py (every Cypher query
the product depends on, with its comment and, optionally, FalkorDB's plan).

    uv run python -m scripts.gen_queries_doc [--explain]
"""

import argparse
import ast
import asyncio
import re
from pathlib import Path

from lineage.graph import queries as Q

ROOT = Path(__file__).parents[1]
SRC = ROOT / "lineage" / "graph" / "queries.py"


def collect_queries() -> list[dict]:
    lines = SRC.read_text().splitlines()
    tree = ast.parse(SRC.read_text())
    out, section = [], "General"
    section_at = {i: m.group(1).strip() for i, l in enumerate(lines) if (m := re.match(r"#\s*---\s*(.+?)\s*-+\s*$", l))}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper() or name.startswith("_"):
            continue
        start = node.lineno - 1
        for i in sorted(section_at):
            if i < start:
                section = section_at[i]
        comment, j = [], start - 1
        while j >= 0 and lines[j].lstrip().startswith("#") and not re.match(r"#\s*---", lines[j].lstrip()):
            comment.insert(0, lines[j].lstrip("# ").rstrip())
            j -= 1
        value = getattr(Q, name)
        cypher = value if isinstance(value, str) else next(iter(value.values())) if isinstance(value, dict) else None
        if cypher:
            out.append({"name": name, "section": section, "comment": " ".join(comment), "cypher": cypher.strip()})
    return out


async def _explain(cypher: str) -> str | None:
    from lineage.db import get_db

    params = sorted(set(re.findall(r"\$(\w+)", cypher)))
    prefix = ("CYPHER " + " ".join(f"{p}=null" for p in params) + " ") if params else ""
    db = await get_db()
    try:
        plan = await db.connection.execute_command("GRAPH.EXPLAIN", "lineage:company", prefix + cypher)
        return "\n".join(x.decode() if isinstance(x, bytes) else str(x) for x in plan)
    except Exception:
        return None
    finally:
        await db.aclose()


async def render(explain: bool) -> str:
    qs = collect_queries()
    out = ["# Cypher queries", "",
           "Every query Lineage depends on, generated from `lineage/graph/queries.py`. "
           "Writes use `UNWIND $rows` + `MERGE` on stable ids, so ingestion is batched and safe to re-run. "
           + ("Plans come from `GRAPH.EXPLAIN` on the real graph." if explain else ""), ""]
    current = None
    for q in qs:
        if q["section"] != current:
            current = q["section"]
            out += [f"## {current}", ""]
        out += [f"### `{q['name']}`", ""]
        if q["comment"]:
            out += [q["comment"], ""]
        out += ["```cypher", q["cypher"], "```", ""]
        if explain and (plan := await _explain(q["cypher"])):
            out += ["<details><summary>Execution plan</summary>", "", "```", plan, "```", "</details>", ""]
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--explain", action="store_true")
    a = ap.parse_args()
    (ROOT / "docs" / "queries.md").write_text(asyncio.run(render(a.explain)))
    print(f"wrote docs/queries.md ({len(collect_queries())} queries)")
