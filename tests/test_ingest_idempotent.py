import json
import shutil
from pathlib import Path

import yaml

from lineage.db import ro
from lineage.ingest.run import run_pipeline

FIX = Path(__file__).parent / "fixtures"


class FakeEmbedder:
    def embed(self, texts):
        return [[0.3] * 384 for _ in texts]


def _data_dir(tmp_path: Path) -> tuple[Path, Path]:
    data, cfg = tmp_path / "raw", tmp_path / "config"
    (data / "peps").mkdir(parents=True)
    (data / "devguide").mkdir()
    (data / "discourse").mkdir()
    shutil.copy(FIX / "peps_sample.json", data / "peps.json")
    shutil.copy(FIX / "pep_sample.rst", data / "peps" / "pep-0102.rst")
    shutil.copy(FIX / "experts_sample.rst", data / "devguide" / "experts.rst")
    topic = json.loads((FIX / "discourse_topic_sample.json").read_text())
    topic["id"] = 1000
    (data / "discourse" / "t-1000.json").write_text(json.dumps(topic))
    cfg.mkdir()
    (cfg / "aliases.yaml").write_text(yaml.safe_dump({"Ann Author": "annauthor"}))
    (cfg / "areas.yaml").write_text(yaml.safe_dump({"argparse": ["Lib/argparse.py"]}))
    (cfg / "focus_peps.yaml").write_text(yaml.safe_dump({"peps": [100, 101, 102]}))
    (cfg / "events.yaml").write_text(yaml.safe_dump([]))
    return data, cfg


async def _counts(g):
    n = (await ro(g, "MATCH (n) RETURN count(n) AS c"))[0]["c"]
    e = (await ro(g, "MATCH ()-[r]->() RETURN count(r) AS c"))[0]["c"]
    d = (await ro(g, "MATCH (d:Decision) RETURN count(d) AS c"))[0]["c"]
    return n, e, d


async def test_offline_pipeline_twice_gives_identical_counts(g, tmp_path):
    data, cfg = _data_dir(tmp_path)
    await run_pipeline(g, data_dir=data, config_dir=cfg, offline=True, skip_github=True, embedder=FakeEmbedder())
    first = await _counts(g)
    await run_pipeline(g, data_dir=data, config_dir=cfg, offline=True, skip_github=True, embedder=FakeEmbedder())
    assert await _counts(g) == first
    assert first[0] > 20
    # the alias was applied, the forum thread linked, and the decision got its announcing post
    assert await ro(g, "MATCH (p:Person {id:'person:annauthor'})-[:AUTHORED]->(:PEP {id:'pep:100'}) RETURN count(p) AS c") == [{"c": 1}]
    out = await ro(g, "MATCH (:Decision {id:'decision:pep:100:accept'})-[:RECORDED_IN]->(po:Post) RETURN po.post_number AS n")
    assert out == [{"n": 2}]
