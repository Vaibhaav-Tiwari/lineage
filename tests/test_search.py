from datetime import date

import pytest

from lineage.db import rw
from lineage.graph.search import hits_to_fragment, hybrid_search
from lineage.schema import ensure_company_schema

DOCS = [
    ("pep:1", "Type parameter syntax", "2022-06-01", "Type parameter syntax for generics: declare generic classes and functions with type parameters in brackets."),
    ("pep:2", "Packaging metadata", "2000-01-01", "Packaging metadata fields for distributions, wheels and the packaging core metadata specification."),
    ("pep:3", "GC tuning", "2010-01-01", "Garbage collector tuning thresholds and generations for the cyclic garbage collector."),
]


@pytest.fixture(scope="module")
def embedder():
    from lineage.ingest.embed import Embedder

    return Embedder()


async def _setup(g, embedder):
    await ensure_company_schema(g)
    vecs = embedder.embed([d[3] for d in DOCS])
    for (pid, title, created, text), v in zip(DOCS, vecs):
        await rw(g, """CREATE (p:PEP {id:$pid, title:$title, number:toInteger(substring($pid, 4)), created:date($created),
                       pagerank:0.1, source_url:'https://peps.python.org/x'})
                       CREATE (:Chunk {id:$pid + ':c0', heading:'Abstract', text:$text, emb:vecf32($v)})-[:PART_OF]->(p)""",
                 {"pid": pid, "title": title, "created": created, "text": text, "v": v})
    # a second, weaker chunk for pep:1 to test de-duplication
    v = embedder.embed(["Unrelated appendix about history."])[0]
    await rw(g, "MATCH (p:PEP {id:'pep:1'}) CREATE (:Chunk {id:'pep:1:c1', heading:'Appendix', text:'Unrelated appendix about history.', emb:vecf32($v)})-[:PART_OF]->(p)", {"v": v})


async def test_vector_ranking_uses_distance_correctly(g, embedder):
    await _setup(g, embedder)
    hits = await hybrid_search(g, "generic type parameters", embedder, k=3)
    assert hits[0]["pep_id"] == "pep:1"
    assert hits[0]["vec_sim"] > hits[-1]["vec_sim"]


async def test_fulltext_alone_finds_keyword(g, embedder):
    await _setup(g, embedder)
    hits = await hybrid_search(g, "packaging", embedder, k=3, weights=(0.0, 1.0, 0.0))
    assert hits[0]["pep_id"] == "pep:2"


async def test_as_of_hides_later_peps(g, embedder):
    await _setup(g, embedder)
    hits = await hybrid_search(g, "generic type parameters", embedder, k=3, as_of=date(2001, 1, 1))
    assert {h["pep_id"] for h in hits} == {"pep:2"}


async def test_one_hit_per_pep_and_fragment(g, embedder):
    await _setup(g, embedder)
    hits = await hybrid_search(g, "generic type parameters", embedder, k=5)
    peps = [h["pep_id"] for h in hits]
    assert len(peps) == len(set(peps))
    frag = hits_to_fragment(hits)
    assert "pep:1" in frag.ids() and any(e["type"] == "PART_OF" for e in frag.edges)
