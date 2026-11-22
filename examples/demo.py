#!/usr/bin/env python3
"""Two-minute tour: build the fixture, audit both stores, gate a session.

    python3 examples/demo.py

Builds the canonical four-claim fixture in a temp directory (one true
claim, one refuted, one stale, one unverifiable), audits it through both
adapters -- a memoryvault-agents MemoryDoc store and a plain CLAUDE.md --
then renders the gated session-start context for the Markdown store.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "fixtures"))

import build_fixture
from memreckon.adapters import MarkdownAdapter, MemoryVaultAdapter
from memreckon.audit import run_audit
from memreckon.gate import render_gate_markdown


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        paths = build_fixture.build(Path(tmp) / "fixture")
        for name, adapter in (
            ("memoryvault", MemoryVaultAdapter()),
            ("markdown", MarkdownAdapter()),
        ):
            result = run_audit(adapter, paths[name], paths["repo"])
            print(f"--- audit of the {name} store ---")
            for entry in result.entries:
                v = result.verdict_for(entry.id)
                print(f"[{v.stamp:<12}] {entry.text}")
            print()
        result = run_audit(MarkdownAdapter(), paths["markdown"], paths["repo"])
        print("--- gated session-start context (markdown store) ---")
        print(render_gate_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
