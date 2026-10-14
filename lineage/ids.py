"""Stable string ids for every node. The same id is used in the company graph
and in agents' Evidence stubs, which is how lineage crosses graphs."""

import re
import unicodedata

# characters NFKD can't decompose into ASCII
_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text.translate(_EXTRA)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def pep(n: int) -> str:
    return f"pep:{int(n)}"


def person(handle: str) -> str:
    return f"person:{handle.strip().lower()}"


def area(name: str) -> str:
    return f"area:{name.strip().lower()}"


def chunk(n: int, i: int) -> str:
    return f"chunk:pep:{int(n)}:{int(i)}"


def decision(n: int, kind: str) -> str:
    return f"decision:pep:{int(n)}:{kind}"


def thread(topic_id: int) -> str:
    return f"thread:{int(topic_id)}"


def post(post_id: int) -> str:
    return f"post:{int(post_id)}"


def pr(n: int) -> str:
    return f"pr:{int(n)}"


def event(s: str) -> str:
    return f"event:{s}"


def team(name: str) -> str:
    return f"team:{slug(name)}"
