from lineage.ingest.identity import IdentityResolver, jaro_winkler

ALIASES = {"Guido van Rossum": "gvanrossum"}


def test_alias_and_github_forms_resolve_to_one_person():
    r = IdentityResolver(ALIASES)
    a = r.resolve(name="Guido van Rossum")
    b = r.resolve(github="gvanrossum")
    c = r.resolve(github="GvanRossum")
    assert a == b == c == "person:gvanrossum"


def test_discourse_handle_is_remembered_once_linked():
    r = IdentityResolver(ALIASES)
    first = r.resolve(discourse="guido", name="Guido van Rossum")
    assert r.resolve(discourse="guido") == first == "person:gvanrossum"


def test_similar_first_names_with_different_last_names_do_not_merge():
    r = IdentityResolver({})
    assert r.resolve(name="Brett Cannon") != r.resolve(name="Brett Slatkin")


def test_near_identical_names_with_same_last_name_merge():
    r = IdentityResolver({})
    assert r.resolve(name="Jelle Zijlstra") == r.resolve(name="Jelle  Zijlstra.")


def test_accented_names_get_ascii_slugs():
    r = IdentityResolver({})
    assert r.resolve(name="Łukasz Langa") == "person:lukasz-langa"


def test_people_rows_union_all_seen_aliases():
    r = IdentityResolver(ALIASES)
    r.resolve(name="Guido van Rossum")
    r.resolve(discourse="guido", github="gvanrossum")
    r.resolve(name="Ann Author")
    rows = {p["id"]: p for p in r.people()}
    assert len(rows) == 2
    g = rows["person:gvanrossum"]
    assert g["github"] == "gvanrossum" and g["discourse"] == "guido" and g["name"] == "Guido van Rossum"
    assert "Guido van Rossum" in g["aliases"]


def test_jaro_winkler_basics():
    assert jaro_winkler("martha", "marhta") > 0.95
    assert jaro_winkler("abc", "xyz") == 0.0


async def test_load_people_sets_handles_on_person_nodes(g):
    from lineage.db import ro
    from lineage.ingest.identity import load_people

    r = IdentityResolver(ALIASES)
    r.resolve(name="Guido van Rossum", discourse="guido")
    await load_people(g, r)
    await load_people(g, r)
    out = await ro(g, "MATCH (p:Person) RETURN p.id AS id, p.github AS gh, p.discourse AS d, p.aliases AS a")
    assert out == [{"id": "person:gvanrossum", "gh": "gvanrossum", "d": "guido", "a": ["Guido van Rossum"]}]
