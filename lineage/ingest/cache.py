"""Fetch-with-cache. Raw source responses are saved under data/raw/ and
committed, so a deploy can rebuild the graph without touching the network."""

import asyncio
import time
from pathlib import Path

import httpx

_last_call: dict[str, float] = {}


async def fetch_cached(url: str, path: Path, min_interval: float = 0.0, headers: dict | None = None) -> bytes:
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    host = httpx.URL(url).host
    wait = _last_call.get(host, 0) + min_interval - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": "lineage-hackathon", **(headers or {})}) as c:
        r = await c.get(url)
    _last_call[host] = time.monotonic()
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content
