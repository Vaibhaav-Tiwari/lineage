"""Plain-language readings of graph results, built from rules (no LLM), so they
also work on the LLM-free public deployment. People are 'they', always."""


def _n(k: int, word: str, plural: str | None = None) -> str:
    return f"{k} {word if k == 1 else (plural or word + 's')}"


def _and(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def explain_departure(w: dict) -> dict:
    name = w["person"].get("name") or w["person"]["id"]
    orphaned, at_risk = w.get("orphaned_areas", []), w.get("at_risk_areas", [])
    split = max(0, (w.get("components_after") or 0) - (w.get("components_before") or 0))
    rank = w.get("bridge_rank")
    major_bridge = bool(rank and rank <= 3)
    important_bridge = bool(rank and rank <= 20)

    if len(orphaned) >= 2 or (orphaned and split):
        verdict = "be badly hurt"
    elif orphaned or at_risk or split or important_bridge:
        verdict = "cope, but it would feel it"
    else:
        verdict = "barely notice"

    bullets = []
    bullets.append(f"{_and(orphaned)} would be left with nobody actively looking after {'it' if len(orphaned) == 1 else 'them'}."
                   if orphaned else "No part of Python would be left without an owner.")
    if at_risk:
        names = ", ".join(a["area"] for a in at_risk)
        bullets.append(f"{_n(len(at_risk), 'part')} of Python ({names}) would depend on just one person.")
    if split and (major_bridge or important_bridge):
        role = "one of the main people connecting different groups" if major_bridge else "an important link between groups"
        bullets.append(f"They are {role} of contributors; without them, {_n(split, 'group')} of contributors would lose touch with the rest.")
    elif split:
        bullets.append(f"Without them, {_n(split, 'group')} of contributors would lose touch with the rest.")
    elif major_bridge:
        bullets.append("They are one of the main people connecting different groups of contributors, though the groups would stay in touch.")
    if w.get("authored_peps"):
        made = f"They wrote {_n(w['authored_peps'], 'proposal')}"
        if w.get("decisions_announced"):
            made += f" and announced {_n(w['decisions_announced'], 'decision')}"
        bullets.append(made + ".")
    basis = w.get("successor_basis", {})
    groups: dict[tuple, list[str]] = {}
    for area, people in w.get("suggested_successors", {}).items():
        if people:
            groups.setdefault((basis.get(area, "collaboration"), tuple(people)), []).append(area)
    for (how, people), areas in groups.items():
        where = " or ".join(areas)
        if how == "commits":
            bullets.append(f"For {where}, {_and(list(people))} already commit there and could take over.")
        else:
            bullets.append(f"Nobody else commits to {where}; the people who worked most closely with them ({_and(list(people))}) are the natural candidates.")
    return {"headline": f"If {name} left, Python would {verdict}.", "bullets": bullets}


def explain_ripple(rep: dict) -> str:
    peps = ", ".join(c.replace("pep:", "PEP ") for c in rep["changed"])
    h = (rep.get("agents") or {}).get("historian") or {"answers": [], "beliefs": [], "actions_blocked": []}
    parts = [f"{peps} has been replaced."]
    soft = len(rep["ripple"].get("soft", []))
    if soft:
        parts.append(f"{_n(soft, 'other proposal')} mention it and should be reviewed.")
    built = []
    if h["answers"]:
        built.append(_n(len(h["answers"]), "answer"))
    if h["beliefs"]:
        built.append(_n(len(h["beliefs"]), "belief"))
    if built:
        parts.append(f"The Historian had {' and '.join(built)} built on it; they are now marked out of date.")
    else:
        parts.append("Nothing the Historian had concluded depended on it.")
    if h["actions_blocked"]:
        parts.append(f"{_n(len(h['actions_blocked']), 'planned action')} {'is' if len(h['actions_blocked']) == 1 else 'are'} on hold.")
    return " ".join(parts)


def explain_drift(a: dict) -> str:
    if a["status"] == "healthy":
        return "The listed owners are the people doing the work."
    if a["status"] == "orphaned":
        return "Nobody is actively looking after this."
    bits = []
    q, u = len(a.get("listed_but_quiet", [])), len(a.get("active_but_unlisted", []))
    if q:
        bits.append(f"{_n(q, 'listed owner')} {'hasn' if q == 1 else 'haven'}'t committed in a year")
    if u:
        bits.append(f"{_n(u, 'active contributor')} {'isn' if u == 1 else 'aren'}'t listed")
    return (", and ".join(bits) + ".").capitalize() if bits else "The ownership list is out of date."
