"""Fetch (and cache) CPython commit history per module since 2015. Needs GITHUB_TOKEN.

    GITHUB_TOKEN=$(gh auth token) uv run python -m scripts.fetch_history
"""

import asyncio
from pathlib import Path

import yaml

from lineage.config import settings
from lineage.ingest.github import fetch_history


async def main():
    token = settings().github_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"} if token else {}
    areas = yaml.safe_load(Path("config/areas.yaml").read_text())
    extra = yaml.safe_load(Path("config/areas_history.yaml").read_text()) or {}
    hist = await fetch_history(areas, extra, Path("data/raw"), headers, offline=not token)
    for a, cs in sorted(hist.items()):
        print(f"{a:14} {len(cs):5} commits")


if __name__ == "__main__":
    asyncio.run(main())
