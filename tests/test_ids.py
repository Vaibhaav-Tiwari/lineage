from lineage import ids


def test_pep_id():
    assert ids.pep(563) == "pep:563"


def test_slug_of_name():
    assert ids.slug("Guido van Rossum") == "guido-van-rossum"


def test_slug_transliterates_accents():
    assert ids.slug("Łukasz Langa") == "lukasz-langa"


def test_person_id_is_lowercased():
    assert ids.person("GVanRossum") == "person:gvanrossum"


def test_other_ids():
    assert ids.chunk(649, 3) == "chunk:pep:649:3"
    assert ids.decision(649, "accept") == "decision:pep:649:accept"
    assert ids.thread(26803) == "thread:26803"
    assert ids.post(1) == "post:1"
    assert ids.pr(12) == "pr:12"
    assert ids.event("pep-563-superseded") == "event:pep-563-superseded"
    assert ids.team("Steering Council") == "team:steering-council"
    assert ids.area("asyncio") == "area:asyncio"
