import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))

import build_fixture
from memreckon.adapters import MarkdownAdapter, MemoryVaultAdapter
from memreckon.frontmatter import parse_frontmatter, split_frontmatter


class TestFrontmatter(unittest.TestCase):
    def test_fixture_doc_parses(self):
        block, _ = split_frontmatter(build_fixture.MEMORYVAULT_DOC)
        self.assertIsNotNone(block)
        meta = parse_frontmatter(block)
        self.assertEqual(meta["title"], "Project state")
        self.assertEqual(meta["sources"], ["session:fixture"])
        self.assertEqual(meta["updated_at"], 1700000000)
        facts = meta["facts"]
        self.assertEqual(len(facts), 4)
        self.assertEqual(facts[0]["subject"], "Dependency requests")
        self.assertEqual(facts[0]["value"], "2.31.0")
        self.assertEqual(facts[2]["subject"], "slugify helper")


class TestMemoryVaultAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = build_fixture.build(Path(self.tmp.name) / "fx")
        self.adapter = MemoryVaultAdapter()

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_doc_entries(self):
        entries = self.adapter.entries(self.paths["memoryvault"])
        self.assertEqual(len(entries), 4)
        by_subject = {e.subject: e for e in entries}
        self.assertEqual(by_subject["Test suite"].value, "all tests pass")
        self.assertEqual(by_subject["Test suite"].updated_at, 1700000000.0)
        self.assertEqual(by_subject["Test suite"].provenance, "session:fixture")
        self.assertIn("#fact[", by_subject["Test suite"].locator)

    def test_json_state_entries(self):
        doc = {
            "path": "project/state.md",
            "title": "Project state",
            "body": "",
            "facts": [
                {"subject": "Test suite", "value": "all tests pass",
                 "source": "session:fixture", "updated_at": 1700000000},
            ],
            "tags": [], "sources": ["session:fixture"], "version": 1,
            "updated_at": 1700000000,
        }
        state = Path(self.tmp.name) / "state.json"
        state.write_text(json.dumps({"memories": [doc]}), encoding="utf-8")
        entries = self.adapter.entries(state)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].text, "Test suite: all tests pass")
        self.assertEqual(entries[0].updated_at, 1700000000.0)

    def test_body_fallback(self):
        doc = Path(self.tmp.name) / "plain.md"
        doc.write_text(
            "# Notes\n\n- **Deploy target**: production\n- **Owner**: platform team\n",
            encoding="utf-8",
        )
        entries = self.adapter.entries(doc)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].subject, "Deploy target")


class TestMarkdownAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = build_fixture.build(Path(self.tmp.name) / "fx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_md_entries(self):
        entries = MarkdownAdapter().entries(self.paths["markdown"])
        texts = [e.text for e in entries]
        self.assertEqual(len(entries), 4)
        self.assertIn("Test suite: all tests pass", texts)
        self.assertIn("slugify helper: defined in src/util.py", texts)
        for e in entries:
            self.assertEqual(e.updated_at, 1700000000.0)


if __name__ == "__main__":
    unittest.main()
