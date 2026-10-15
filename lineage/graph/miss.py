"""Why the Historian has no answer, worked out from the graph rather than guessed.

missing      the PEP number isn't in Python's index (offer the nearest ones)
not_yet      it exists, but only after the date on the dial (offer today / that date)
unrecorded   it exists, but nothing recorded answers this question (offer what can be asked)
unrecognised no PEP, module or person named (offer an example that existed at the dial date)
system       the language model couldn't be reached: not the question's fault
"""

import re
from datetime import date

from lineage.db import ro
from lineage.graph import queries as Q
from lineage.graph.tools import HISTORY_START, ownership_known

_PEP = re.compile(r"\bPEP[\s-]*(\d{1,4})\b", re.I)
_LATER = "The dial hides anything later than the date you picked."


def _today(as_of: date) -> list[dict]:
    return [{"label": "Ask as of today", "as_of": None}]


async def explain_miss(g, question: str, as_of: date | None, error: str | None = None) -> dict:
    if error:
        short = error if len(error) <= 120 else error[:117] + "…"
        return {"kind": "system", "text": f"Claude couldn't be reached ({short}), so this is not about your question. "
                                          "Try again in a few minutes.",
                "actions": [{"label": "Try again", "question": question}]}

    day = as_of.isoformat() if as_of else None
    m = _PEP.search(question)
    if m:
        n = int(m.group(1))
        rows = await ro(g, Q.PEP_BRIEF, {"n": n})
        if not rows:
            near = await ro(g, Q.NEAREST_PEPS, {"n": n})
            named = " and ".join(f'PEP {r["number"]}, "{r["title"]}"' for r in near)
            return {"kind": "missing",
                    "text": f"There's no PEP {n} in Python's index." + (f" The nearest are {named}." if near else ""),
                    "actions": [{"label": f"Ask about PEP {r['number']}",
                                 "question": question[:m.start()] + f"PEP {r['number']}" + question[m.end():]} for r in near]}
        p = rows[0]
        if as_of and p["created"] and p["created"] > day:
            return {"kind": "not_yet",
                    "text": f"As of {day}, PEP {n} hadn't been written yet: it was created on {p['created']}. {_LATER}",
                    "actions": _today(as_of) + [{"label": f"Move the dial to {p['created']}", "as_of": p["created"]}]}
        status = "" if as_of else f" ({p['status']})"
        return {"kind": "unrecorded",
                "text": f'The graph has PEP {n}, "{p["title"]}"{status}, but nothing recorded answers this exact question. '
                        "It can tell you why a proposal was decided, who decided it and when.",
                "actions": [{"label": "Ask why it was decided", "question": f"Why was PEP {n} decided this way?"},
                            {"label": "Ask who decided it", "question": f"Who decided PEP {n}?"}]}

    area = await ro(g, Q.AREAS_NAMED_IN, {"q": question})
    if area:
        name = area[0]["name"]
        firsts = await ro(g, Q.FIRST_PEP_ABOUT, {"name": name}) + await ro(g, Q.FIRST_PEP_CONCERNING, {"name": name})
        first = min(firsts, key=lambda r: r["created"] or "9999") if firsts else None
        if as_of and first and first["created"] and first["created"] > day:
            return {"kind": "not_yet",
                    "text": f"As of {day} there is nothing about {name} yet: the first proposal about it, "
                            f"PEP {first['number']}, dates from {first['created']}. {_LATER}",
                    "actions": _today(as_of) + [{"label": f"Move the dial to {first['created']}", "as_of": first["created"]}]}
        if not ownership_known(as_of):
            return {"kind": "unrecorded",
                    "text": f"Commit history is only held from {HISTORY_START.year}, so who worked on {name} "
                            f"can't be answered as of {day}. {_LATER}",
                    "actions": _today(as_of)}
        return {"kind": "unrecorded",
                "text": f"The graph knows {name}, but nothing recorded answers this exact question. "
                        "It can tell you who knows the module and which proposals shaped it.",
                "actions": [{"label": f"Ask who knows {name}", "question": f"Who should I ask about {name}?"}]}

    ex = await ro(g, Q.EXAMPLE_PEP_AT, {"as_of": day})
    actions = [{"label": f"Try: Who decided PEP {ex[0]['number']}?", "question": f"Who decided PEP {ex[0]['number']}?"}] if ex else []
    return {"kind": "unrecognised",
            "text": "I couldn't tell which proposal, module or person this is about. "
                    "Name a PEP number, a Python module or a person.",
            "actions": actions + (_today(as_of) if as_of else [])}
