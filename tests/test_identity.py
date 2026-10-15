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


def test_github_name_lets_a_handle_join_the_person_known_by_name():
    r = IdentityResolver({}, github_names={"viicos": "Victorien Plot"})
    a = r.resolve(name="Victorien Plot")
    assert r.resolve(github="viicos") == a
    rows = {p["id"]: p for p in r.people()}
    assert rows[a]["github"] == "viicos" and rows[a]["name"] == "Victorien Plot"


def test_github_name_fills_in_display_name_for_a_new_handle():
    r = IdentityResolver({}, github_names={"kumaraditya303": "Kumar Aditya"})
    pid = r.resolve(github="KumarAditya303")
    assert pid == "person:kumaraditya303"
    assert r.people()[0]["name"] == "Kumar Aditya"


def test_same_name_but_different_github_accounts_stay_apart():
    r = IdentityResolver({}, github_names={"dsmith1": "David Smith", "dsmith2": "David Smith"})
    assert r.resolve(github="dsmith1") != r.resolve(github="dsmith2")


def test_a_fuller_name_replaces_a_first_name_only_display_name():
    r = IdentityResolver({"Victorien Plot": "viicos"}, github_names={"viicos": "Victorien"})
    pid = r.resolve(github="viicos")
    assert r.resolve(name="Victorien Plot") == pid
    assert r.people()[0]["name"] == "Victorien Plot"
