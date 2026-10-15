from pathlib import Path

README = (Path(__file__).parents[1] / "README.md").read_text()

REQUIRED = [
    "Tracks: Agent Memory and Coordination, Company Brain",
    "Graph data model",
    "Cypher queries and algorithms",
    "Setup",
    "Live demo",
    "Demo video",
    "Evaluation",
    "AI assistance disclosure",
    "Data sources and licenses",
]


def test_readme_has_every_required_section():
    missing = [h for h in REQUIRED if h not in README]
    assert not missing, missing


def test_readme_links_point_to_real_files():
    for rel in ["docs/queries.md", "eval/results-graph-only.md", "docs/specs/2026-10-14-lineage-design.md"]:
        assert rel in README and (Path(__file__).parents[1] / rel).exists(), rel
