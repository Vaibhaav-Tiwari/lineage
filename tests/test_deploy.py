"""What the public deployment relies on: hourly reset, allowed origins, one fork at a time, seeding on first boot."""

import asyncio
import uuid

import pytest

from lineage.api import main as api
from lineage.db import rw
from lineage.deploy import seed_if_empty

from tests.test_api import app_env  # noqa: F401  (fixture)


async def test_auto_reset_resets_after_every_interval_and_survives_a_failed_reset():
    calls, sleeps = [], []

    async def reset():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database busy")

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await api.auto_reset(reset, minutes=60, sleep=sleep)
    assert sleeps == [3600, 3600, 3600] and len(calls) == 2


def test_allowed_origins_come_from_the_environment(monkeypatch):
    from lineage.config import settings

    monkeypatch.setenv("CORS_ORIGINS", "https://lineage.example, https://other.example")
    settings.cache_clear()
    try:
        app = api.create_app(prefix="t")
        cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        assert cors.kwargs["allow_origins"] == ["https://lineage.example", "https://other.example"]
    finally:
        settings.cache_clear()


async def test_what_if_forks_run_one_at_a_time(app_env, monkeypatch):  # noqa: F811
    c, _, _ = app_env
    running, peak = 0, 0

    async def fake_departure(db, ids, base):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return {"ok": True}

    monkeypatch.setattr(api, "departure_impact", fake_departure)
    rs = await asyncio.gather(*(c.post("/org/whatif", json={"person_id": "person:bob"}) for _ in range(3)))
    assert [r.status_code for r in rs] == [200, 200, 200] and peak == 1


async def test_seed_builds_the_graph_only_when_it_is_missing(db):
    name = f"test:{uuid.uuid4().hex[:8]}"
    runs = []

    async def fake_pipeline(g, data_dir, config_dir, **kw):
        runs.append(kw)
        await rw(g, "CREATE (:PEP {id: 'pep:1'})")

    assert await seed_if_empty(db, name, pipeline=fake_pipeline) == "seeded"
    assert runs == [{"offline": True, "rewind": True, "quiet": False}]
    assert await seed_if_empty(db, name, pipeline=fake_pipeline) == "present"
    assert len(runs) == 1
    await db.select_graph(name).delete()
