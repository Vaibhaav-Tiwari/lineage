"""Edges computed from loaded data: COLLABORATED, CONCERNS, and PEP pagerank."""

import re
from collections import defaultdict
from itertools import combinations

from lineage.db import ro, rw, write_batch
from lineage.graph import queries as Q

THREAD_WEIGHT_CAP = 5
MIN_AREA_NAME = 4  # 're', 'io', 'gc'... match far too much prose


async def derive_collaboration(g) -> int:
    w: dict[tuple[str, str], int] = defaultdict(int)
    for r in await ro(g, Q.CO_AUTHOR_PAIRS):
        w[(r["a"], r["b"])] += 3 * r["n"]
    shared_threads: dict[tuple[str, str], int] = defaultdict(int)
    for r in await ro(g, Q.THREAD_POSTERS):
        for a, b in combinations(sorted(set(r["people"])), 2):
            shared_threads[(a, b)] += 1
    for pair, n in shared_threads.items():
        w[pair] += min(n, THREAD_WEIGHT_CAP)
    for r in await ro(g, Q.CO_AREA_PAIRS):
        w[(r["a"], r["b"])] += 2 * r["n"]
    rows = [{"a": a, "b": b, "w": v} for (a, b), v in w.items()]
    await write_batch(g, Q.UPSERT_COLLABORATED, rows)
    return len(rows)


def _word(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w.]){re.escape(name)}(?![\w])", re.I)


async def derive_concerns(g) -> int:
    titles = await ro(g, Q.PEP_TITLES)
    rows = set()
    for area in await ro(g, Q.AREAS):
        name = (area["name"] or "").strip()
        if len(name) < MIN_AREA_NAME:
            continue
        pat = _word(name)
        for t in titles:
            if t["title"] and pat.search(t["title"]):
                rows.add((t["id"], area["id"]))
        query = '"' + re.sub(r"[^\w ]", " ", name).strip() + '"'
        mentions: dict[str, int] = defaultdict(int)
        try:
            hits = await ro(g, Q.CHUNKS_MENTIONING, {"q": query})
        except Exception:
            continue  # no full-text index yet / unparsable query
        for h in hits:
            mentions[h["pep"]] += len(pat.findall(h["text"] or ""))
        rows |= {(pep, area["id"]) for pep, n in mentions.items() if n >= 2}
    await write_batch(g, Q.UPSERT_CONCERNS, [{"pep": p, "area": a} for p, a in sorted(rows)])
    return len(rows)


async def compute_pagerank(g) -> None:
    await rw(g, Q.PAGERANK_PEPS)
