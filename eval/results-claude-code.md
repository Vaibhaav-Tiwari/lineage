# Evaluation — backend `claude-code`

- **Correct:** 20/20 (100%)
- **Citation recall** (answerable questions): 100%
- **Correct abstentions** on out-of-corpus questions: 3/3
- **Median time per question:** 12.1 s

- **Ripple recall:** 100%, precision 100% (8 PEPs flagged, 8 expected; missed none, extra none)

## Graph tool latency (ms)

| Tool | Calls | p50 | p95 |
|---|---|---|---|
| decision_path | 15 | 10.8 | 15.1 |
| pep_timeline | 1 | 11.5 | 11.5 |
| search | 3 | 27.8 | 48.2 |
| who_knows | 2 | 7.1 | 12.9 |

## Questions

| Question | Correct | Citation recall | Missing | Seconds |
|---|---|---|---|---|
| Who announced the acceptance of PEP 649, and when? | ✅ | 100% | – | 15.6 |
| Who announced that PEP 695, the type parameter syntax, was accepted? | ✅ | 100% | – | 12.1 |
| Who announced the decision on PEP 701? | ✅ | 100% | – | 12.4 |
| When was PEP 749 accepted, and who announced it? | ✅ | 100% | – | 11.9 |
| Who announced the acceptance of PEP 688? | ✅ | 100% | – | 12.9 |
| Who announced that PEP 692 was accepted? | ✅ | 100% | – | 9.1 |
| Who accepted PEP 740? | ✅ | 100% | – | 12.2 |
| Who wrote PEP 572, assignment expressions? | ✅ | 100% | – | 12.2 |
| Who are the authors of PEP 484, type hints? | ✅ | 100% | – | 15.7 |
| Which PEP superseded PEP 241? | ✅ | 100% | – | 10.9 |
| Which PEP superseded PEP 5, the guidelines for language evolution? | ✅ | 100% | – | 11.4 |
| What superseded PEP 345, metadata for Python software packages 1.2? | ✅ | 100% | – | 10.3 |
| Who wrote PEP 634 on structural pattern matching? | ✅ | 100% | – | 14.8 |
| Who wrote PEP 20, the Zen of Python? | ✅ | 100% | – | 9.4 |
| Who should I ask about asyncio today? Who is actually committing to it? | ✅ | 100% | – | 17.5 |
| Who is actively working on the typing module right now? | ✅ | 100% | – | 17.6 |
| What was the status of PEP 563 in mid-2020? | ✅ | 100% | – | 10.8 |
| How does Rust's borrow checker handle lifetimes? | ✅ | – | – | 14.7 |
| What is the population of Paris? | ✅ | – | – | 11.5 |
| Which JavaScript framework did the Steering Council pick for the python.org website redesign? | ✅ | – | – | 11.8 |
