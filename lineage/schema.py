"""Indexes and constraints for each kind of graph. Every function is idempotent."""

import asyncio

from lineage.db import ro

COMPANY_LABELS = ("PEP", "Person", "Area", "Chunk", "Decision", "Thread", "Post", "PR", "Event", "Team")
EMBED_DIM = 384  # BAAI/bge-small-en-v1.5


async def _try(g, cypher: str) -> None:
    try:
        await g.query(cypher)
    except Exception as e:  # re-running is fine; anything else is a real error
        if "already indexed" not in str(e):
            raise


async def _range(g, label: str, prop: str) -> None:
    await _try(g, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")


async def _unique(g, label: str, prop: str) -> None:
    # FalkorDB requires a range index on the property before a UNIQUE constraint
    await _range(g, label, prop)
    existing = await ro(g, "CALL db.constraints() YIELD type, label, properties RETURN type, label, properties")
    if not any(c["type"] == "UNIQUE" and c["label"] == label and c["properties"] == [prop] for c in existing):
        await g.create_node_unique_constraint(label, prop)


async def _mandatory(g, label: str, prop: str) -> None:
    existing = await ro(g, "CALL db.constraints() YIELD type, label, properties RETURN type, label, properties")
    if not any(c["type"] == "MANDATORY" and c["label"] == label and c["properties"] == [prop] for c in existing):
        await g.create_node_mandatory_constraint(label, prop)


async def _wait_constraints(g, timeout: float = 10.0) -> None:
    """Constraints are built asynchronously (PENDING → OPERATIONAL)."""
    for _ in range(int(timeout / 0.1)):
        rows = await ro(g, "CALL db.constraints() YIELD status RETURN status")
        if all(r["status"] == "OPERATIONAL" for r in rows):
            return
        if any(r["status"] == "FAILED" for r in rows):
            raise RuntimeError(f"constraint creation failed: {rows}")
        await asyncio.sleep(0.1)
    raise TimeoutError("constraints still pending")


async def ensure_company_schema(g) -> None:
    for label in COMPANY_LABELS:
        await _unique(g, label, "id")
    await _range(g, "PEP", "number")
    await _range(g, "PEP", "status")
    await _range(g, "Decision", "at")
    # records the product cannot make sense of are refused by the database, not just by the ingest code
    await _mandatory(g, "PEP", "number")
    await _mandatory(g, "PEP", "title")
    await _mandatory(g, "Decision", "kind")
    for label in ("Chunk", "Post"):
        await _try(g, f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.emb) "
                      f"OPTIONS {{dimension:{EMBED_DIM}, similarityFunction:'cosine'}}")
    await _try(g, "CREATE FULLTEXT INDEX FOR (n:PEP) ON (n.title)")
    await _try(g, "CREATE FULLTEXT INDEX FOR (n:Chunk) ON (n.text)")
    await _try(g, "CREATE FULLTEXT INDEX FOR (n:Post) ON (n.text)")
    await _wait_constraints(g)


async def ensure_agent_schema(g) -> None:
    for label in ("Belief", "Answer", "Action", "Outbox"):
        await _unique(g, label, "id")
    await _range(g, "Evidence", "id")
    await _unique(g, "Evidence", "ref")
    await _wait_constraints(g)


async def ensure_user_schema(g) -> None:
    await _unique(g, "Episode", "id")
    await _unique(g, "Interest", "area_ref")
    await _wait_constraints(g)


async def ensure_shared_schema(g) -> None:
    await _unique(g, "FixTask", "id")
    await _unique(g, "Agent", "name")
    await _unique(g, "FaqEntry", "id")
    await _wait_constraints(g)
