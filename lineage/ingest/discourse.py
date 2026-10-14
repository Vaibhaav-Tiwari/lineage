"""discuss.python.org topic JSON → Thread, Post, POSTED, decision provenance.

Topics are public JSON (no login). The first page has 20 posts; a specific
post (e.g. the acceptance announcement, often #40+) comes from
/posts/by_number/<topic>/<n>.json.
"""

import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from lineage import ids
from lineage.db import rw, write_batch
from lineage.graph import queries as Q

BASE = "https://discuss.python.org"
MAX_TEXT = 2000


def parse_discuss_url(url: str | None) -> tuple[int, int | None] | None:
    if not url:
        return None
    u = urlparse(url.strip())
    if u.netloc != "discuss.python.org" or not u.path.startswith("/t/"):
        return None
    segs = [s for s in u.path[3:].split("/") if s]
    if segs and not segs[0].isdigit():
        segs = segs[1:]  # drop slug
    nums = [int(s) for s in segs if s.isdigit()]
    if not nums:
        return None
    return nums[0], (nums[1] if len(nums) > 1 else None)


def html_to_text(cooked: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", cooked or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


@dataclass
class TopicRows:
    thread: dict
    posts: list[dict] = field(default_factory=list)


def parse_post(p: dict, topic_id: int, slug: str) -> dict:
    return {
        "id": ids.post(p["id"]),
        "post_number": p["post_number"],
        "username": p.get("username"),
        "name": p.get("name") or None,
        "date": p["created_at"][:10],
        "text": html_to_text(p.get("cooked", ""))[:MAX_TEXT],
        "url": f"{BASE}/t/{slug}/{topic_id}/{p['post_number']}",
        "reply_to": p.get("reply_to_post_number"),
    }


def parse_topic(raw: dict) -> TopicRows:
    tid, slug = raw["id"], raw.get("slug") or str(raw["id"])
    thread = {
        "id": ids.thread(tid), "topic_id": tid, "title": raw.get("title"),
        "date": raw["created_at"][:10], "posts_count": raw.get("posts_count", 0), "url": f"{BASE}/t/{slug}/{tid}",
    }
    posts = [parse_post(p, tid, slug) for p in raw.get("post_stream", {}).get("posts", [])]
    return TopicRows(thread, posts)


async def load_topic(g, rows: TopicRows, resolver, embedder, pep_ids: list[str] = ()) -> None:
    await rw(g, Q.UPSERT_THREAD, rows.thread)
    vecs = embedder.embed([p["text"][:1200] or "(empty)" for p in rows.posts]) if rows.posts else []
    out = [
        {**p, "thread_id": rows.thread["id"], "emb": v,
         "person_id": resolver.resolve(discourse=p["username"], name=p["name"])}
        for p, v in zip(rows.posts, vecs)
    ]
    await write_batch(g, Q.UPSERT_POSTS, out, chunk=100)
    await write_batch(g, Q.LINK_PEP_THREAD, [{"pep_id": pid, "thread_id": rows.thread["id"]} for pid in pep_ids])


async def link_decision_provenance(g, pep_n: int, resolution_url: str, rows: TopicRows) -> None:
    parsed = parse_discuss_url(resolution_url)
    if not parsed:
        return
    _, post_number = parsed
    post = next((p for p in rows.posts if p["post_number"] == post_number), None) if post_number else None
    if post:
        await rw(g, Q.LINK_DECISION_POST, {"pep_id": ids.pep(pep_n), "post_id": post["id"]})
    else:
        await rw(g, Q.LINK_DECISION_THREAD, {"pep_id": ids.pep(pep_n), "thread_id": rows.thread["id"]})
