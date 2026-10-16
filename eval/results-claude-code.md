# Evaluation — backend `claude-code`

- **Correct:** 20/20 (100%)
- **Citation recall** (answerable questions): 100%
- **Correct abstentions** on out-of-corpus questions: 3/3
- **Median time per question:** 9.9 s

- **Ripple recall:** 100%, precision 100% (8 PEPs flagged, 8 expected; missed none, extra none)

## Graph tool latency (ms)

| Tool | Calls | p50 | p95 |
|---|---|---|---|
| decision_path | 15 | 12.8 | 18.7 |
| search | 3 | 59.3 | 60.0 |
| who_knows | 2 | 7.4 | 12.5 |

## Questions

| Question | Correct | Citation recall | Missing | Seconds |
|---|---|---|---|---|
| Who announced the acceptance of PEP 649, and when? | ✅ | 100% | – | 11.2 |
| Who announced that PEP 695, the type parameter syntax, was accepted? | ✅ | 100% | – | 9.6 |
| Who announced the decision on PEP 701? | ✅ | 100% | – | 13.9 |
| When was PEP 749 accepted, and who announced it? | ✅ | 100% | – | 15.1 |
| Who announced the acceptance of PEP 688? | ✅ | 100% | – | 8.9 |
| Who announced that PEP 692 was accepted? | ✅ | 100% | – | 11.3 |
| Who accepted PEP 740? | ✅ | 100% | – | 10.1 |
| Who wrote PEP 572, assignment expressions? | ✅ | 100% | – | 6.5 |
| Who are the authors of PEP 484, type hints? | ✅ | 100% | – | 6.8 |
| Which PEP superseded PEP 241? | ✅ | 100% | – | 9.9 |
| Which PEP superseded PEP 5, the guidelines for language evolution? | ✅ | 100% | – | 12.1 |
| What superseded PEP 345, metadata for Python software packages 1.2? | ✅ | 100% | – | 9.9 |
| Who wrote PEP 634 on structural pattern matching? | ✅ | 100% | – | 8.3 |
| Who wrote PEP 20, the Zen of Python? | ✅ | 100% | – | 7.6 |
| Who should I ask about asyncio today? Who is actually committing to it? | ✅ | 100% | – | 16.0 |
| Who is actively working on the typing module right now? | ✅ | 100% | – | 14.1 |
| What was the status of PEP 563 in mid-2020? | ✅ | 100% | – | 11.5 |
| How does Rust's borrow checker handle lifetimes? | ✅ | – | – | 8.9 |
| What is the population of Paris? | ✅ | – | – | 9.7 |
| Which JavaScript framework did the Steering Council pick for the python.org website redesign? | ✅ | – | – | 9.3 |
