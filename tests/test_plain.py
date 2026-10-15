from lineage.graph.plain import explain_departure, explain_drift, explain_ripple


def _w(**kw):
    base = {"person": {"id": "person:x", "name": "Ada Example"}, "orphaned_areas": [], "at_risk_areas": [],
            "components_before": 8, "components_after": 8, "bridge_rank": 300, "people_ranked": 900,
            "authored_peps": 0, "decisions_announced": 0, "suggested_successors": {}, "successor_basis": {}}
    return {**base, **kw}


def test_departure_barely_noticed():
    p = explain_departure(_w())
    assert p["headline"] == "If Ada Example left, Python would barely notice."
    assert "No part of Python would be left without an owner." in p["bullets"]


def test_departure_feels_it_with_plain_bullets_and_neutral_pronouns():
    p = explain_departure(_w(at_risk_areas=[{"area": "__main__", "remaining": 1}, {"area": "deepfreeze", "remaining": 1}],
                             components_after=10, bridge_rank=2, authored_peps=50, decisions_announced=1,
                             suggested_successors={"__main__": ["Barry Warsaw", "Victor Stinner"]},
                             successor_basis={"__main__": "collaboration"}))
    assert p["headline"] == "If Ada Example left, Python would cope, but it would feel it."
    text = " ".join(p["bullets"])
    assert "2 parts of Python (__main__, deepfreeze) would depend on just one person." in text
    assert "one of the main people connecting different groups" in text and "2 groups" in text
    assert "worked most closely with them" in text and "Barry Warsaw" in text
    assert "wrote 50 proposals" in text
    assert " he " not in f" {text.lower()} " and " she " not in f" {text.lower()} "


def test_departure_badly_hurt_when_modules_orphaned():
    p = explain_departure(_w(orphaned_areas=["configparser", "xml"], suggested_successors={"configparser": ["Brett Cannon"]},
                             successor_basis={"configparser": "commits"}))
    assert p["headline"].endswith("Python would be badly hurt.")
    assert "configparser and xml would be left with nobody actively looking after them." in p["bullets"]
    assert any("Brett Cannon already commit" in b for b in p["bullets"])


def test_ripple_plain_summary():
    rep = {"changed": ["pep:563"], "summary": "PEP 563 is superseded by PEP 649 + PEP 749.",
           "ripple": {"soft": ["pep:1"] * 8, "chunks": ["c"] * 34},
           "agents": {"historian": {"answers": ["a"], "beliefs": ["b1", "b2"], "actions_blocked": ["x"]}}, "fixtasks": ["t"] * 8}
    s = explain_ripple(rep)
    assert s.startswith("PEP 563 has been replaced.")
    assert "8 other proposals mention it" in s and "1 answer and 2 beliefs" in s and "1 planned action is on hold" in s


def test_drift_plain_lines():
    assert explain_drift({"status": "healthy", "listed_but_quiet": [], "active_but_unlisted": []}) == "The listed owners are the people doing the work."
    assert explain_drift({"status": "orphaned", "listed_but_quiet": [], "active_but_unlisted": []}) == "Nobody is actively looking after this."
    assert explain_drift({"status": "drifting", "listed_but_quiet": ["a", "b"], "active_but_unlisted": ["c"]}) == \
        "2 listed owners haven't committed in a year, and 1 active contributor isn't listed."


def test_same_successors_for_several_areas_are_merged():
    p = explain_departure(_w(suggested_successors={"__main__": ["A", "B"], "deepfreeze": ["A", "B"]},
                             successor_basis={"__main__": "collaboration", "deepfreeze": "collaboration"}))
    assert sum("natural candidates" in b for b in p["bullets"]) == 1
    assert any("__main__ or deepfreeze" in b for b in p["bullets"])
