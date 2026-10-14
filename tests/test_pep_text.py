import json
from pathlib import Path

import pytest

from lineage.db import ro, rw
from lineage.ingest.identity import IdentityResolver
from lineage.ingest.pep_text import load_pep_text, parse_pep_rst
from lineage.ingest.peps import load_peps, parse_peps
from lineage.schema import ensure_company_schema

FIX = Path(__file__).parent / "fixtures"
TEXT = (FIX / "pep_sample.rst").read_text()


def test_headers_and_links():
    doc = parse_pep_rst(200, TEXT)
    assert doc.headers["Title"] == "Synthetic Sample PEP"
    assert doc.delegate == "Carol Coder"
    assert doc.discussions_to == "https://discuss.python.org/t/pep-200-sample/3000"
    assert doc.resolution.startswith("`03-Mar-2023")
    assert "https://discuss.python.org/t/pep-200-sample/3000" in doc.thread_urls
    assert "https://discuss.python.org/t/pep-200-sample/3000/42" in doc.thread_urls


def test_references_count_both_forms_and_skip_self():
    doc = parse_pep_rst(200, TEXT)
    assert doc.references == {101: 3}


def test_chunks_split_on_sections_and_size():
    doc = parse_pep_rst(200, TEXT)
    headings = [c["heading"] for c in doc.chunks]
    assert headings[0] == "Abstract" and "Specification" in headings
    assert headings.count("Motivation") >= 2  # long section split on paragraphs
    assert all(0 < len(c["text"]) <= 1200 for c in doc.chunks)
    assert not any("=====" in c["text"] for c in doc.chunks)


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


async def test_load_pep_text_builds_chunks_refs_delegate(g):
    await ensure_company_schema(g)
    await load_peps(g, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
    await rw(g, "CREATE (:PEP {id:'pep:200', number:200, title:'Synthetic Sample PEP'})")
    doc = parse_pep_rst(200, TEXT)
    await load_pep_text(g, 200, doc, FakeEmbedder(), IdentityResolver({}))
    await load_pep_text(g, 200, doc, FakeEmbedder(), IdentityResolver({}))  # idempotent
    n = await ro(g, "MATCH (c:Chunk)-[:PART_OF]->(:PEP {id:'pep:200'}) RETURN count(c) AS c")
    assert n == [{"c": len(doc.chunks)}]
    assert await ro(g, "MATCH (:PEP {id:'pep:200'})-[r:REFERENCES]->(:PEP {id:'pep:101'}) RETURN r.count AS c") == [{"c": 3}]
    assert await ro(g, "MATCH (p:Person)-[:DELEGATE_FOR]->(:PEP {id:'pep:200'}) RETURN p.id AS id") == [{"id": "person:carol-coder"}]


@pytest.mark.slow
def test_real_embedder_shape():
    from lineage.ingest.embed import Embedder

    vecs = Embedder().embed(["a", "b"])
    assert len(vecs) == 2 and len(vecs[0]) == 384
