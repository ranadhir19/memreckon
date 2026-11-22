# memreckon

**The memory auditor for AI coding agents.** Memory stores remember;
nothing checks whether what they remember is still true. memreckon
re-checks the mechanically checkable claims in an agent memory store
against the live repository and stamps every entry:

| Stamp | Meaning |
|---|---|
| **VERIFIED** | Re-checked against the live repo just now, and it holds. |
| **REFUTED** | The live repo contradicts the claim. Quarantine it — with the evidence. |
| **STALE** | Still true, but what it describes changed after the memory was written; never re-confirmed. |
| **UNVERIFIABLE** | Not mechanically checkable, or the check could not run. Never upgraded, never guessed. |

Every audit is written to a **hash-chained ledger** (tamper-evident: any
later edit to a verdict breaks the chain), and a **gate mode** renders
session-start context in which REFUTED memories are quarantined with
their contradicting evidence instead of being injected as fact.

Pure Python standard library. Offline. No model calls. The store is
never modified.

## Why this exists

Agent memory is a crowded field — cross-agent stores, memory platforms,
and plain `CLAUDE.md`/`AGENTS.md` files all compete on capture,
retrieval, and portability. In a 2026-11-20 landscape audit of twelve
memory systems (from the 118k-star plugins to bi-temporal knowledge
graphs), exactly one capability scored zero for **every** entrant:
*verification* — re-checking a remembered claim against the current
state of the world before the next agent trusts it. Memories are
fabricated at write time, go stale silently, and are then injected into
the next session's most trusted context. memreckon is the missing
read-path layer.

## Where it sits

memreckon is **not a memory store** and does not compete with one. It
complements **[memoryvault-agents](https://github.com/ranadhir19/memoryvault-agents)**
— a unified cross-harness memory store with provenance-carrying source
adapters — as its **read-path verification layer**: memoryvault is the
store and the write path; memreckon is the auditor that sits on top of
it (and on top of any other store whose memory is files). Its first
adapter targets memoryvault's formats precisely so the store can be
audited from day one.

It is also a complement, not a rival, to integrity tools such as
memattest: those prove a memory is *unaltered since it was recorded*;
memreckon checks whether what it says is *true now*. A memory can be
perfectly intact and perfectly wrong.

## How it works

```
memory store ──adapter──▶ entries ──extract──▶ claims ──check──▶ verdicts
                                                              │
                                        hash-chained ledger ◀─┤
                                        gate context (SessionStart) ◀─┘
```

1. **Adapters** lift entries out of a store (see below).
2. **Extraction** classifies each entry into a checkable claim type —
   deterministically, by pattern, never by model. Anything that matches
   nothing is a *judgment* claim.
3. **Checkers** settle each claim against the live repository: stat the
   file, grep the symbol, read the lockfile, run the named test suite,
   read the config, ask git.
4. **Staleness rule:** if the substantive check passes but an artifact
   the claim is about changed *after* the memory recorded it, the stamp
   is STALE, not VERIFIED. REFUTED always wins over STALE.
5. **Ledger + gate:** verdicts are appended to the hash-chained ledger;
   gate mode renders trusted / stale / unverified / quarantined
   sections for session start.

### Claim taxonomy (v1)

| Claim type | Example memory | How it is checked |
|---|---|---|
| `file-exists` | "the parser lives in src/parser.py" | stat the path |
| `symbol-exists` | "slugify helper: defined in src/util.py" | search for a definition (or reference) |
| `test-outcome` | "all tests pass" | run the repo's own suite (validate.py, pytest, or unittest discovery) |
| `dependency-version` | "requests: 2.31.0" | read requirements/pyproject/package.json/Cargo/go manifests and lockfiles |
| `config-value` | "the config setting MAX_RETRIES is 5" | search .env/ini/toml/json/yaml config for the key |
| `command-outcome` | "`make build` exits 0" | only with `--run-commands`; otherwise UNVERIFIABLE |
| `git-state` | "the current branch is main" | `git branch` / `rev-parse` / `status` |
| `judgment` | "the team prefers small PRs" | not mechanically checkable → UNVERIFIABLE, with the reason stated |

Honesty details that matter:

- A dependency claimed but absent from every manifest is **REFUTED**
  (manifests are the repo's own declaration of what it depends on).
- A config key found in no config file is **UNVERIFIABLE**, not refuted
  — the value may legitimately come from the environment. Absence is
  only treated as proof where the source is exhaustive.
- A symbol found only as a reference, not a definition, is VERIFIED
  with `match_kind: reference-only` in the evidence — the weaker match
  is disclosed, not hidden.

## Quickstart

```bash
# The two-minute tour: builds the canonical fixture and audits it
python3 examples/demo.py

# Audit a real store against a live repo
PYTHONPATH=src python3 -m memreckon audit \
    --store ./memory --repo ./my-project --out ./audit-out
#   -> audit-out/ledger.jsonl, audit-out/report.md

# Gate a session start (exit 1 if anything is REFUTED)
PYTHONPATH=src python3 -m memreckon gate \
    --store ./CLAUDE.md --repo ./my-project --fail-on-refuted

# Verify a ledger's hash chain
PYTHONPATH=src python3 -m memreckon verify-ledger ./audit-out/ledger.jsonl

# Serve the tools over stdio (MCP-style JSON-RPC)
PYTHONPATH=src python3 -m memreckon mcp
```

Or install it: `pip install .` provides the `memreckon` command.

### The fixture

`fixtures/build_fixture.py` builds the canonical exhibit — one repo, two
stores, four claims with four known stamps (a true dependency claim, a
"tests pass" claim the failing fixture suite refutes, a symbol claim
gone stale, and a team preference no machine can check). It is *built*,
not shipped as files, because the STALE stamp depends on file mtimes,
which do not survive copying. The test suite rebuilds it for every run.

## Adapters

| Adapter | Stores it reads |
|---|---|
| `memoryvault` | memoryvault-agents: a directory of MemoryDoc Markdown files (frontmatter `facts`), a single such file, or the JSON state export (`{"memories": [...]}`) |
| `markdown` | Any plain-Markdown memory: `CLAUDE.md`, `AGENTS.md`, ai-memory-style files — every bullet/paragraph line is an entry |
| `auto` (default) | Detects memoryvault formats first, falls back to markdown |

New stores implement one small protocol (`can_handle` + `entries`) and
register in `ADAPTERS`; extraction, checking, the ledger, and the gate
do not change. An ai-memory wiki or a Mem0 export is an adapter away.

The MCP-style server exposes three tools — `audit_store`,
`gate_context`, `verify_ledger` — as newline-delimited JSON-RPC 2.0
over stdio, in the MCP tool-call shape, stdlib only.

## Safety posture

- **Read-only everywhere.** memreckon never writes to the store, the
  repo, or any external system. Its only outputs are the ledger, the
  report, and the gate context you asked for.
- **Commands are opt-in.** A memory that names a command is *not*
  executed by default — that is exactly the channel a poisoned memory
  would abuse. Command-outcome claims are UNVERIFIABLE unless the
  operator passes `--run-commands`. (Running the repo's own test suite
  is the one exception: it is the repo's code, and it is what a
  test-outcome claim is about.)
- **The ledger is tamper-evident, not identity-signed.** The hash chain
  proves a ledger was not altered after being written; it does not
  prove who wrote it. Stated plainly, on purpose.

## Limitations (v1, stated)

- One claim per entry: the first matching pattern wins. A memory that
  bundles three claims in one sentence gets its dominant claim audited
  and the rest ride along unexamined — the report's claim type shows
  which reading was checked.
- Extraction is pattern-based. It will miss checkable claims phrased
  unusually (they land in UNVERIFIABLE, the safe direction) and the
  taxonomy covers coding-agent memory, not chat preferences.
- Staleness needs timestamps. A store that records none gets substantive
  stamps with `freshness: not assessed` in the evidence.

## Validation

```bash
python3 validate.py
```

Runs the full test suite (58 tests), a byte-compile, the four-stamp
fixture proof through the public API on both adapters, a ledger
round-trip, required-file checks, and a secrets scan. Exit 0 is the
repo's deploy gate.

## Pre-registered kill criterion

From the landscape analysis that scoped this build: run v1 against
three real stores (a memoryvault graph, an ai-memory-style wiki, a
CLAUDE.md corpus). **Kill if** fewer than 40% of entries are
mechanically checkable, **or** the false-REFUTED rate exceeds 5% on a
seeded ground-truth suite, **or** no one outside the author's own
projects runs an audit within 45 days of public release.

## License

MIT — see [LICENSE](LICENSE). Name collision record: [NAME_CHECK.md](NAME_CHECK.md).
Compliance record: [COMPLIANCE.md](COMPLIANCE.md).
