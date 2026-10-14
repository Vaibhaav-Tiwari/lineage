"""Build lineage:company from public sources.

    uv run python -m lineage.ingest.run [--offline] [--skip-github] [--rewind-replays]

Raw responses are cached under data/raw/ (committed), so --offline rebuilds the
graph with no network at all — that's what the deploy uses.
"""

import argparse
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path

import yaml

from lineage.config import settings
from lineage.db import get_db
from lineage.ingest import discourse as D
from lineage.ingest import github as GH
from lineage.ingest.cache import fetch_cached
from lineage.ingest.derive import compute_pagerank, derive_collaboration, derive_concerns
from lineage.ingest.events import load_events, rewind_event, upsert_events
from lineage.ingest.experts import EXPERTS_URL, load_experts, parse_experts
from lineage.ingest.identity import IdentityResolver, load_people
from lineage.ingest.pep_text import load_pep_text, parse_pep_rst
from lineage.ingest.peps import PEPS_URL, load_peps, parse_peps, parse_resolution
from lineage.schema import ensure_company_schema

PEP_SRC = "https://raw.githubusercontent.com/python/peps/main/peps/pep-{n:04d}.rst"


def _yaml(path: Path, default):
    return (yaml.safe_load(path.read_text()) if path.exists() else None) or default


class _Log:
    def __init__(self, quiet: bool):
        self.quiet, self.t0 = quiet, time.monotonic()

    def __call__(self, msg: str):
        if not self.quiet:
            print(f"[{time.monotonic() - self.t0:6.1f}s] {msg}", flush=True)


async def _fetch_texts(numbers: list[int], data_dir: Path, offline: bool) -> dict[int, str]:
    sem = asyncio.Semaphore(16)

    async def one(n: int):
        async with sem:
            try:
                raw = await fetch_cached(PEP_SRC.format(n=n), data_dir / "peps" / f"pep-{n:04d}.rst", offline=offline)
            except Exception:
                return n, None  # e.g. a few PEPs are .txt/.md or missing
            return n, raw.decode("utf-8", "replace") if raw else None

    return {n: t for n, t in await asyncio.gather(*(one(n) for n in numbers)) if t}


async def _github(g, cfg: Path, data_dir: Path, raw_peps: dict, resolver, offline: bool, log) -> None:
    token = settings().github_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"} if token else {}
    if not token and not offline:
        log("github: no GITHUB_TOKEN — using cache only")
        offline = True
    since = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 365 * 86400))
    for area, paths in _yaml(cfg / "areas.yaml", {}).items():
        commits = []
        for path in paths:
            for page in range(1, 6):
                key = f"commits-{area}-{path.replace('/', '_')}-{page}.json"
                url = f"{GH.API}/repos/python/cpython/commits?path={path}&since={since}&per_page=100&page={page}"
                raw = await fetch_cached(url, data_dir / "github" / key, headers=headers, offline=offline)
                batch = json.loads(raw) if raw else []
                commits += batch
                if len(batch) < 100:
                    break
        await GH.load_revealed(g, GH.aggregate_commits(commits, area), resolver)
    focus = set(_yaml(cfg / "focus_peps.yaml", {}).get("peps", []))
    items = []
    for n in sorted(focus):
        p = raw_peps.get(str(n), {})
        if p.get("status") not in ("Final", "Accepted") or p.get("type") != "Standards Track":
            continue
        q = f'repo:python/cpython is:pr is:merged "PEP {n}" in:title'
        url = f"{GH.API}/search/issues?q={q}&per_page=50"
        raw = await fetch_cached(url, data_dir / "github" / f"search-pep-{n}.json", min_interval=2.1, headers=headers, offline=offline)
        if raw:
            items += [i for i in json.loads(raw).get("items", []) if n in GH.extract_pep_refs(i.get("title", ""))]
    await GH.load_prs(g, items, resolver)
    log(f"github: {len(items)} PEP-implementing PRs")


async def run_pipeline(g, data_dir: Path, config_dir: Path, offline: bool = False, skip_github: bool = False,
                       embedder=None, rewind: bool = False, quiet: bool = True) -> None:
    log = _Log(quiet)
    data_dir, cfg = Path(data_dir), Path(config_dir)
    if embedder is None:
        from lineage.ingest.embed import Embedder

        embedder = Embedder()
    await ensure_company_schema(g)

    raw_peps = json.loads(await fetch_cached(PEPS_URL, data_dir / "peps.json", offline=offline))
    rows = parse_peps(raw_peps)
    resolver = IdentityResolver(_yaml(cfg / "aliases.yaml", {}))
    await load_peps(g, rows, person_id=lambda name: resolver.resolve(name=name))
    log(f"peps: {len(rows.peps)} PEPs, {len(rows.decisions)} decisions, {len(rows.supersedes)} supersedes")

    texts = await _fetch_texts([p["number"] for p in rows.peps], data_dir, offline)
    thread_peps: dict[int, set[str]] = defaultdict(set)
    resolutions: dict[int, tuple[int, str]] = {}  # topic -> (pep, resolution url)
    for i, p in enumerate(rows.peps, 1):
        n = p["number"]
        if i % 50 == 0:
            log(f"pep text: {i}/{len(rows.peps)}")
        urls = [u for u in (p.get("discussions_to"), p.get("resolution_url")) if u]
        if n in texts:
            doc = parse_pep_rst(n, texts[n])
            await load_pep_text(g, n, doc, embedder, resolver)
            urls += doc.thread_urls
        for u in urls:
            parsed = D.parse_discuss_url(u)
            if parsed:
                thread_peps[parsed[0]].add(p["id"])
        res = D.parse_discuss_url(p.get("resolution_url"))
        if res:
            resolutions.setdefault(res[0], (n, p["resolution_url"]))
    log(f"pep text: {len(texts)} PEPs chunked + embedded; {len(thread_peps)} forum threads referenced")

    await load_experts(g, parse_experts((await fetch_cached(EXPERTS_URL, data_dir / "devguide" / "experts.rst", offline=offline) or b"").decode()), resolver)
    log("experts index loaded")

    for j, tid in enumerate(sorted(thread_peps), 1):
        if j % 25 == 0:
            log(f"forum: {j}/{len(thread_peps)} threads")
        raw = await fetch_cached(f"{D.BASE}/t/{tid}.json", data_dir / "discourse" / f"t-{tid}.json", min_interval=1.0, offline=offline)
        if not raw:
            continue
        topic = json.loads(raw)
        trows = D.parse_topic(topic)
        if tid in resolutions:
            pep_n, res_url = resolutions[tid]
            _, post_n = D.parse_discuss_url(res_url)
            if post_n and post_n not in {p["post_number"] for p in trows.posts}:
                pr = await fetch_cached(f"{D.BASE}/posts/by_number/{tid}/{post_n}.json",
                                        data_dir / "discourse" / f"p-{tid}-{post_n}.json", min_interval=1.0, offline=offline)
                if pr:
                    trows.posts.append(D.parse_post(json.loads(pr), tid, topic.get("slug") or str(tid)))
        await D.load_topic(g, trows, resolver, embedder, pep_ids=sorted(thread_peps[tid]))
        if tid in resolutions:
            await D.link_decision_provenance(g, resolutions[tid][0], resolutions[tid][1], trows)
    log(f"forum: {len(thread_peps)} threads processed")

    if not skip_github:
        await _github(g, cfg, data_dir, raw_peps, resolver, offline, log)

    await load_people(g, resolver)
    log(f"people: {len(resolver.people())} resolved")
    collab = await derive_collaboration(g)
    concerns = await derive_concerns(g)
    await compute_pagerank(g)
    log(f"derived: {collab} collaborations, {concerns} PEP→area links, pagerank")

    specs = load_events(cfg / "events.yaml") if (cfg / "events.yaml").exists() else []
    await upsert_events(g, specs)
    if rewind:
        for e in specs:
            if e.replay:
                await rewind_event(g, e.slug)
                log(f"rewound event {e.slug} (ready to replay)")


async def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", default="lineage:company")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--config-dir", default="config")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-github", action="store_true")
    ap.add_argument("--rewind-replays", action="store_true")
    a = ap.parse_args()
    db = await get_db()
    g = db.select_graph(a.graph)
    await run_pipeline(g, a.data_dir, a.config_dir, offline=a.offline, skip_github=a.skip_github,
                       rewind=a.rewind_replays, quiet=False)
    await db.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
