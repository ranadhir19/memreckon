# Name check — memreckon

Checked 2026-11-20, before any code was written, across web search,
GitHub, and PyPI.

## Candidates

| Candidate | Verdict | Evidence |
|---|---|---|
| **memattest** | REJECTED — real collision | A live PyPI package (`memattest` 1.0.2) already provides "AI agent memory attestation": hooks record memory writes into a Merkle log and a session-start pass verifies integrity/provenance. Same territory, same word. (Its own docs state it does *not* prove a memory's content is true — which is precisely memreckon's job; the tools are complements, but the name was taken.) |
| **memseal** | REJECTED — real collision | MemSeal is a live AI-security product doing deterministic provenance tracking for AI agent long-term memory (indexed in AI tool directories, compared against other agent-security tools). |
| **memreckon** | **CHOSEN — clean** | Exact-match web search for "memreckon" returns no product, package, or repository of that name; a GitHub-scoped search returns no results; no PyPI project of that name surfaced. Near names are distinct names for unrelated things: "mem-re" (an event-ticket digital-experience platform), MemoRec (a metamodeling recommender from a 2022 journal paper), RecMem (a recommendation-systems paper), `reckon` (a Python memoization library). None is an agent-memory tool, and none shares the full name. |

## Fit

The name follows the portfolio's reckoning family — runreckon (the eval
tool), effectreckon (effect verification for app control) — and says
what the tool does: it *reckons* memory, i.e. settles its accounts
against reality. "Membrane"/"mnemo"-style names were not pursued: that
namespace is densely occupied (mem0, memkernel, membrick, mnemolith,
memtether, memoire) and every occupant is a *store*, which memreckon
deliberately is not.
