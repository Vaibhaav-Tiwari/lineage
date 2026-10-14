"""Hybrid retrieval: vector similarity + full-text keywords + PEP pagerank.

FalkorDB's vector index has no filtered search, so we over-fetch (k×3) and
filter/expand in Cypher. One best hit is kept per PEP.
"""

import re
from datetime import date

from lineage.db import ro
from lineage.graph import queries as Q
from lineage.graph.subgraph import Fragment

DEFAULT_WEIGHTS = (0.6, 0.3, 0.1)  # vector, full-text, pagerank


def _ft_query(text: str) -> str | None:
    words = [w for w in re.findall(r"[A-Za-z0-9_]+", text) if len(w) > 2]
    return " | ".join(words) if words else None


async def hybrid_search(g, query: str, embedder, k: int = 8, as_of: date | None = None,
                        weights: tuple[float, float, float] = DEFAULT_WEIGHTS) -> list[dict]:
    wv, wf, wp = weights
    params = {"k": k * 3, "as_of": as_of.isoformat() if as_of else None}
    cands: dict[str, dict] = {}

    def add(row, vec_sim=0.0, ft=0.0):
        h = cands.setdefault(row["id"], {**{f: row[f] for f in ("id", "label", "heading", "pep_id", "title", "number", "url")},
                                         "snippet": (row["text"] or "")[:400], "pagerank": row["pagerank"] or 0.0,
                                         "vec_sim": 0.0, "ft_score": 0.0})
        h["vec_sim"] = max(h["vec_sim"], vec_sim)
        h["ft_score"] = max(h["ft_score"], ft)

    if wv:
        q = embedder.embed([query])[0]
        for cypher in (Q.VECTOR_CHUNKS, Q.VECTOR_POSTS):
            try:
                rows = await ro(g, cypher, {**params, "q": q})
            except Exception:
                rows = []  # e.g. no Post vector index yet
            for r in rows:
                add(r, vec_sim=1.0 - float(r["dist"]))
    ftq = _ft_query(query)
    if wf and ftq:
        for cypher in (Q.FULLTEXT_CHUNKS, Q.FULLTEXT_PEP_TITLES):
            try:
                rows = await ro(g, cypher, {**params, "q": ftq})
            except Exception:
                rows = []
            for r in rows:
                add(r, ft=float(r["ft"]))
    if not cands:
        return []
    max_ft = max(h["ft_score"] for h in cands.values()) or 1.0
    max_pr = max(h["pagerank"] for h in cands.values()) or 1.0
    for h in cands.values():
        h["score"] = wv * h["vec_sim"] + wf * (h["ft_score"] / max_ft) + wp * (h["pagerank"] / max_pr)
    best: dict[str, dict] = {}
    for h in sorted(cands.values(), key=lambda h: h["score"], reverse=True):
        best.setdefault(h["pep_id"], h)
    return list(best.values())[:k]


def hits_to_fragment(hits: list[dict]) -> Fragment:
    frag = Fragment(meta={"hits": [{k: h[k] for k in ("id", "pep_id", "title", "heading", "snippet", "url")} for h in hits]})
    for h in hits:
        frag.nodes.append({"id": h["pep_id"], "label": "PEP", "props": {"title": h["title"], "number": h["number"]}})
        if h["id"] != h["pep_id"]:
            frag.nodes.append({"id": h["id"], "label": h["label"], "props": {"heading": h["heading"], "url": h["url"]}})
            rel = "PART_OF" if h["label"] == "Chunk" else "DISCUSSES"
            frag.edges.append({"src": h["id"], "dst": h["pep_id"], "type": rel, "props": {}})
    return frag.merge(Fragment())
