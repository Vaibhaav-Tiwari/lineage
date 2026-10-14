import pytest

from lineage.db import ro, rw
from lineage.schema import (
    COMPANY_LABELS,
    ensure_agent_schema,
    ensure_company_schema,
    ensure_shared_schema,
    ensure_user_schema,
)


async def _indexes(g) -> dict[tuple[str, str], set[str]]:
    rows = await ro(g, "CALL db.indexes() YIELD label, types RETURN label, types")
    out = {}
    for r in rows:
        for prop, kinds in r["types"].items():
            out[(r["label"], prop)] = set(kinds)
    return out


async def test_company_schema_is_idempotent_and_complete(g):
    await ensure_company_schema(g)
    await ensure_company_schema(g)  # second run must not fail
    idx = await _indexes(g)
    for label in COMPANY_LABELS:
        assert "RANGE" in idx[(label, "id")], label
    assert "VECTOR" in idx[("Chunk", "emb")]
    assert "VECTOR" in idx[("Post", "emb")]
    assert "FULLTEXT" in idx[("PEP", "title")]
    assert "FULLTEXT" in idx[("Chunk", "text")]
    assert "FULLTEXT" in idx[("Post", "text")]
    cons = await ro(g, "CALL db.constraints() YIELD type, label, properties, status RETURN type, label, properties, status")
    pep_unique = [c for c in cons if c["type"] == "UNIQUE" and c["label"] == "PEP" and c["properties"] == ["id"]]
    assert pep_unique and pep_unique[0]["status"] == "OPERATIONAL"


async def test_unique_id_rejects_duplicates(g):
    await ensure_company_schema(g)
    await rw(g, "CREATE (:PEP {id:'pep:1'})")
    with pytest.raises(Exception, match="(?i)unique constraint"):
        await rw(g, "CREATE (:PEP {id:'pep:1'})")


async def test_agent_schema(g):
    await ensure_agent_schema(g)
    idx = await _indexes(g)
    for label in ("Evidence", "Belief", "Answer", "Action"):
        assert "RANGE" in idx[(label, "id")], label
    assert "RANGE" in idx[("Evidence", "ref")]


async def test_user_and_shared_schema(g):
    await ensure_user_schema(g)
    await ensure_shared_schema(g)
    idx = await _indexes(g)
    assert "RANGE" in idx[("Episode", "id")]
    assert "RANGE" in idx[("Interest", "area_ref")]
    assert "RANGE" in idx[("FixTask", "id")]
    assert "RANGE" in idx[("Agent", "name")]
