"""PEP source (reStructuredText) → Chunks (+embeddings), REFERENCES, delegate.

PEP files are very regular: an RFC-822-style header block, then sections whose
titles are underlined with = - ~ ^. Simple rules beat a full RST parser here.
"""

import re
from dataclasses import dataclass, field

from lineage import ids
from lineage.db import write_batch
from lineage.graph import queries as Q

MAX_CHUNK = 1200
_UNDERLINE = re.compile(r"^([=\-~^*#+\"'`])\1{2,}\s*$")
_REF = re.compile(r"(?:\bPEP[\s-]*(\d{1,4})\b|:pep:`(?:[^`<]*<)?(\d{1,4})>?`|peps\.python\.org/pep-(\d{4}))")
_DISCUSS = re.compile(r"https://discuss\.python\.org/t/[^\s<>`,]+")


@dataclass
class PepDoc:
    headers: dict = field(default_factory=dict)
    chunks: list[dict] = field(default_factory=list)
    references: dict[int, int] = field(default_factory=dict)
    delegate: str | None = None
    discussions_to: str | None = None
    resolution: str | None = None
    thread_urls: list[str] = field(default_factory=list)


def _headers(lines: list[str]) -> tuple[dict, int]:
    headers, key, i = {}, None, 0
    for i, line in enumerate(lines):
        if not line.strip():
            return headers, i
        if line[0].isspace() and key:
            headers[key] += " " + line.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            headers[key] = val.strip()
    return headers, i + 1


def _sections(lines: list[str]) -> list[tuple[str, str]]:
    out, heading, buf = [], "Preamble", []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and not _UNDERLINE.match(line) and _UNDERLINE.match(nxt) and len(nxt.strip()) >= len(line.strip()):
            out.append((heading, "\n".join(buf)))
            heading, buf = line.strip(), []
            i += 2
            continue
        if not _UNDERLINE.match(line):  # drop overlines / stray rules
            buf.append(line)
        i += 1
    out.append((heading, "\n".join(buf)))
    return [(h, t.strip()) for h, t in out if t.strip()]


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK:
        return [text]
    pieces, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > MAX_CHUNK:  # a single huge paragraph
            pieces.append(para[:MAX_CHUNK])
            para = para[MAX_CHUNK:]
        if cur and len(cur) + len(para) + 2 > MAX_CHUNK:
            pieces.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        pieces.append(cur)
    return [p for p in pieces if p.strip()]


def _strip_email(person: str) -> str:
    return re.sub(r"\s*<[^>]*>", "", person).strip()


def parse_pep_rst(n: int, text: str) -> PepDoc:
    lines = text.splitlines()
    headers, start = _headers(lines)
    body = lines[start:]
    doc = PepDoc(headers=headers)
    if headers.get("PEP-Delegate"):
        doc.delegate = _strip_email(headers["PEP-Delegate"].split(",")[0])
    doc.discussions_to = headers.get("Discussions-To") or None
    doc.resolution = headers.get("Resolution") or None
    seen = []
    for key in ("Discussions-To", "Post-History", "Resolution"):
        for url in _DISCUSS.findall(headers.get(key, "")):
            if url not in seen:
                seen.append(url)
    doc.thread_urls = seen
    body_text = "\n".join(body)
    for m in _REF.finditer(body_text):
        target = int(next(g for g in m.groups() if g))
        if target != n:
            doc.references[target] = doc.references.get(target, 0) + 1
    for heading, text_ in _sections(body):
        if heading.lower() in ("copyright", "footnotes", "references"):
            continue
        for piece in _split(text_):
            doc.chunks.append({"heading": heading, "text": piece})
    return doc


async def load_pep_text(g, n: int, doc: PepDoc, embedder, resolver) -> None:
    title = doc.headers.get("Title", "")
    vecs = embedder.embed([f"PEP {n}: {title} — {c['heading']}\n{c['text']}" for c in doc.chunks]) if doc.chunks else []
    rows = [
        {"id": ids.chunk(n, i), "pep_id": ids.pep(n), "heading": c["heading"], "text": c["text"], "idx": i, "emb": v}
        for i, (c, v) in enumerate(zip(doc.chunks, vecs))
    ]
    await write_batch(g, Q.UPSERT_CHUNKS, rows, chunk=100)
    refs = [{"src": ids.pep(n), "dst": ids.pep(t), "count": c} for t, c in sorted(doc.references.items())]
    await write_batch(g, Q.UPSERT_REFERENCES, refs)
    if doc.delegate:
        pid = resolver.resolve(name=doc.delegate)
        await write_batch(g, Q.UPSERT_DELEGATES, [{"pep_id": ids.pep(n), "person_id": pid, "name": doc.delegate}])
