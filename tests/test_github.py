import json
from pathlib import Path

from lineage.db import ro
from lineage.ingest.github import aggregate_commits, extract_pep_refs, load_prs, load_revealed
from lineage.ingest.identity import IdentityResolver
from lineage.ingest.peps import load_peps, parse_peps
from lineage.schema import ensure_company_schema

FIX = Path(__file__).parent / "fixtures"


def test_aggregate_commits_counts_per_login_and_skips_deleted_accounts():
    rows = aggregate_commits(json.loads((FIX / "gh_commits_sample.json").read_text()), "argparse")
    by = {r["github"]: r for r in rows}
    assert set(by) == {"alice", "dave"}
    assert by["alice"]["count"] == 3 and by["alice"]["last_at"] == "2026-06-15"
    assert by["dave"]["area"] == "argparse"


def test_extract_pep_refs():
    assert extract_pep_refs("gh-123: Implement PEP 695 (and PEP 696)") == [695, 696]
    assert extract_pep_refs("Fix pepper") == []
    assert extract_pep_refs("PEP-649: lazy annotations") == [649]


async def test_load_revealed_and_prs(g):
    await ensure_company_schema(g)
    await load_peps(g, parse_peps(json.loads((FIX / "peps_sample.json").read_text())))
    r = IdentityResolver({})
    await load_revealed(g, aggregate_commits(json.loads((FIX / "gh_commits_sample.json").read_text()), "argparse"), r)
    out = await ro(g, "MATCH (:Person {id:'person:alice'})-[c:COMMITTED_TO]->(:Area {id:'area:argparse'}) RETURN c.count AS n, toString(c.last_at) AS last")
    assert out == [{"n": 3, "last": "2026-06-15"}]
    await load_prs(g, json.loads((FIX / "gh_search_sample.json").read_text())["items"], r)
    impl = await ro(g, "MATCH (pr:PR)-[:IMPLEMENTS]->(p:PEP) RETURN pr.id AS pr, p.id AS pep ORDER BY pep")
    assert impl == [{"pr": "pr:1", "pep": "pep:102"}, {"pr": "pr:1", "pep": "pep:105"}]
    assert await ro(g, "MATCH (:Person {id:'person:dave'})-[:AUTHORED_PR]->(:PR {id:'pr:1'}) RETURN count(*) AS c") == [{"c": 1}]
    assert await ro(g, "MATCH (pr:PR {id:'pr:2'}) RETURN count(pr) AS c") == [{"c": 0}]  # mentions no PEP


def test_user_display_name_ignores_blank_and_handle_echo():
    from lineage.ingest.github import user_display_name

    assert user_display_name({"login": "viicos", "name": " Victorien Plot "}) == "Victorien Plot"
    assert user_display_name({"login": "abc", "name": None}) is None
    assert user_display_name({"login": "abc", "name": "ABC"}) is None


async def test_fetch_github_names_reads_cache_offline(tmp_path):
    from lineage.ingest.github import fetch_github_names

    d = tmp_path / "github" / "users"
    d.mkdir(parents=True)
    (d / "viicos.json").write_text(json.dumps({"login": "viicos", "name": "Victorien Plot"}))
    names = await fetch_github_names(["Viicos", "missing"], tmp_path, headers={}, offline=True)
    assert names == {"viicos": "Victorien Plot"}
