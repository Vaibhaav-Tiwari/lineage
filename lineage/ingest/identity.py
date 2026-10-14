"""One Person per human, whatever name they appear under.

Order: manual alias map → exact GitHub handle → known forum handle →
same normalised name → Jaro-Winkler ≥ 0.92 with an identical last name →
new id. The last-name guard stops "Brett Cannon" merging with "Brett Slatkin".
"""

from lineage import ids


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(lb, i + window + 1)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    sa = [a[i] for i in range(la) if ma[i]]
    sb = [b[j] for j in range(lb) if mb[j]]
    transpositions = sum(x != y for x, y in zip(sa, sb)) / 2
    jaro = (matches / la + matches / lb + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def _norm(name: str) -> str:
    return " ".join(ids.slug(name).split("-"))


class IdentityResolver:
    def __init__(self, aliases: dict[str, str]):
        self._alias = {_norm(k): v.lower() for k, v in aliases.items()}
        self._by_github: dict[str, str] = {}
        self._by_discourse: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self._people: dict[str, dict] = {}

    def _lookup_name(self, n: str) -> str | None:
        if n in self._by_name:
            return self._by_name[n]
        last = n.split()[-1] if n else ""
        for known, pid in self._by_name.items():
            if known.split()[-1:] == [last] and jaro_winkler(n, known) >= 0.92:
                return pid
        return None

    def resolve(self, name: str | None = None, github: str | None = None, discourse: str | None = None) -> str:
        gh = github.strip().lower() if github else None
        dsc = discourse.strip().lower() if discourse else None
        n = _norm(name) if name else None
        if n and not gh and n in self._alias:
            gh = self._alias[n]
        pid = (
            (self._by_github.get(gh) if gh else None)
            or (self._by_discourse.get(dsc) if dsc else None)
            or (self._lookup_name(n) if n else None)
        )
        if pid is None:
            pid = ids.person(gh) if gh else ids.person(ids.slug(name)) if name else ids.person(f"dsc-{dsc}")
        p = self._people.setdefault(pid, {"id": pid, "name": None, "github": None, "discourse": None, "aliases": []})
        if name:
            p["name"] = p["name"] or name.strip()
            if name.strip() not in p["aliases"]:
                p["aliases"].append(name.strip())
            self._by_name.setdefault(n, pid)
        if gh:
            p["github"] = p["github"] or gh
            self._by_github.setdefault(gh, pid)
        if dsc:
            p["discourse"] = p["discourse"] or dsc
            self._by_discourse.setdefault(dsc, pid)
        return pid

    def people(self) -> list[dict]:
        return list(self._people.values())


async def load_people(g, resolver: IdentityResolver) -> None:
    from lineage.db import write_batch
    from lineage.graph import queries as Q

    await write_batch(g, Q.UPSERT_PEOPLE, resolver.people())
