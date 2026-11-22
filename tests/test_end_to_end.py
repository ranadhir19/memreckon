"""The four-stamp proof: one fixture, two store adapters, exact stamps.

For each adapter (memoryvault-agents MemoryDoc store, plain CLAUDE.md),
the audit of the canonical fixture must produce exactly:

  Dependency requests  -> VERIFIED
  Test suite           -> REFUTED   (the fixture suite has a failing test)
  slugify helper       -> STALE     (util.py changed after the memory)
  Review style         -> UNVERIFIABLE (a judgment, not a checkable claim)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))

import build_fixture
from memreckon import model
from memreckon.adapters import MarkdownAdapter, MemoryVaultAdapter
from memreckon.audit import run_audit
from memreckon.gate import gate_payload, render_gate_markdown
from memreckon.ledger import verify_ledger

EXPECTED = {
    "Dependency requests": model.VERIFIED,
    "Test suite": model.REFUTED,
    "slugify helper": model.STALE,
    "Review style": model.UNVERIFIABLE,
}


class FourStampCase:
    """Mixin: not a TestCase itself, so discovery only runs the subclasses."""

    adapter = None
    store_key = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "fx"
        self.paths = build_fixture.build(root)
        self.ledger = Path(self.tmp.name) / "ledger.jsonl"
        self.result = run_audit(
            self.adapter,
            self.paths[self.store_key],
            self.paths["repo"],
            ledger_path=self.ledger,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_stamps(self):
        got = {}
        for entry in self.result.entries:
            verdict = self.result.verdict_for(entry.id)
            for key in EXPECTED:
                if entry.text.startswith(key):
                    got[key] = verdict.stamp
        self.assertEqual(got, EXPECTED)

    def test_counts(self):
        counts = self.result.counts()
        self.assertEqual(counts["total"], 4)
        for stamp in model.STAMPS:
            self.assertEqual(counts[stamp], 1, stamp)

    def test_ledger_written_and_valid(self):
        ok, problems = verify_ledger(self.ledger)
        self.assertTrue(ok, problems)

    def test_gate_quarantines_refuted(self):
        md = render_gate_markdown(self.result)
        trusted = md.split("## Trusted")[1].split("##")[0]
        quarantined = md.split("## QUARANTINED")[1]
        self.assertIn("Dependency requests", trusted)
        self.assertNotIn("Test suite", trusted)
        self.assertIn("Test suite", quarantined)
        payload = gate_payload(self.result)
        self.assertEqual(len(payload["trusted"]), 1)
        self.assertEqual(len(payload["stale"]), 1)
        self.assertEqual(len(payload["unverified"]), 1)
        self.assertEqual(len(payload["quarantined"]), 1)
        self.assertIn(
            "contradicting_evidence", payload["quarantined"][0]
        )


class TestMemoryVaultStore(FourStampCase, unittest.TestCase):
    adapter = MemoryVaultAdapter()
    store_key = "memoryvault"


class TestMarkdownStore(FourStampCase, unittest.TestCase):
    adapter = MarkdownAdapter()
    store_key = "markdown"


class TestMemoryVaultJsonState(unittest.TestCase):
    def test_json_state_same_stamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fx"
            paths = build_fixture.build(root)
            doc = {
                "path": "project-state.md",
                "title": "Project state",
                "body": "",
                "facts": [
                    {"subject": "Dependency requests", "value": "2.31.0",
                     "source": "session:fixture", "updated_at": 1700000000},
                    {"subject": "Test suite", "value": "all tests pass",
                     "source": "session:fixture", "updated_at": 1700000000},
                    {"subject": "slugify helper", "value": "defined in src/util.py",
                     "source": "session:fixture", "updated_at": 1700000000},
                    {"subject": "Review style",
                     "value": "the team prefers small, frequent pull requests",
                     "source": "session:fixture", "updated_at": 1700000000},
                ],
                "tags": [], "sources": ["session:fixture"], "version": 1,
                "updated_at": 1700000000,
            }
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"memories": [doc]}), encoding="utf-8")
            result = run_audit(MemoryVaultAdapter(), state, paths["repo"])
            got = {}
            for entry in result.entries:
                verdict = result.verdict_for(entry.id)
                for key in EXPECTED:
                    if entry.text.startswith(key):
                        got[key] = verdict.stamp
            self.assertEqual(got, EXPECTED)


if __name__ == "__main__":
    unittest.main()
