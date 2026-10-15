# Evaluation — backend `claude-code`

- **Correct:** 20/20 (100%)
- **Citation recall** (answerable questions): 100%
- **Correct abstentions** on out-of-corpus questions: 3/3
- **Median time per question:** 11.6 s

- **Ripple recall:** 100%, precision 100% (8 PEPs flagged, 8 expected; missed none, extra none)

## Graph tool latency (ms)

| Tool | Calls | p50 | p95 |
|---|---|---|---|
| decision_path | 7 | 53.1 | 152.3 |
| pep_timeline | 1 | 58.9 | 58.9 |
| search | 1 | 165.8 | 165.8 |
| who_knows | 2 | 22.7 | 78.0 |

## Questions

| Question | Correct | Citation recall | Missing | Seconds |
|---|---|---|---|---|
| Who announced the acceptance of PEP 649, and when? | ✅ | 100% | – | 15.2 |
| Who announced that PEP 695, the type parameter syntax, was accepted? | ✅ | 100% | – | 11.4 |
| Who announced the decision on PEP 701? | ✅ | 100% | – | 14.1 |
| When was PEP 749 accepted, and who announced it? | ✅ | 100% | – | 12.1 |
| Who announced the acceptance of PEP 688? | ✅ | 100% | – | 11.7 |
| Who announced that PEP 692 was accepted? | ✅ | 100% | – | 8.6 |
| Who accepted PEP 740? | ✅ | 100% | – | 11.5 |
| Who wrote PEP 572, assignment expressions? | ✅ | 100% | – | 8.3 |
| Who are the authors of PEP 484, type hints? | ✅ | 100% | – | 11.2 |
| Which PEP superseded PEP 241? | ✅ | 100% | – | 9.0 |
| Which PEP superseded PEP 5, the guidelines for language evolution? | ✅ | 100% | – | 10.6 |
| What superseded PEP 345, metadata for Python software packages 1.2? | ✅ | 100% | – | 13.2 |
| Who wrote PEP 634 on structural pattern matching? | ✅ | 100% | – | 12.0 |
| Who wrote PEP 20, the Zen of Python? | ✅ | 100% | – | 10.4 |
| Who should I ask about asyncio today? Who is actually committing to it? | ✅ | 100% | – | 20.1 |
| Who is actively working on the typing module right now? | ✅ | 100% | – | 14.8 |
| What was the status of PEP 563 in mid-2020? | ✅ | 100% | – | 14.3 |
| How does Rust's borrow checker handle lifetimes? | ✅ | – | – | 8.7 |
| What is the population of Paris? | ✅ | – | – | 10.1 |
| Which JavaScript framework did the Steering Council pick for the python.org website redesign? | ✅ | – | – | 32.4 |
