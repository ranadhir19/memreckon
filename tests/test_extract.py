import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memreckon import model
from memreckon.extract import extract_claim
from memreckon.model import Entry


def entry(text: str) -> Entry:
    return Entry(id="e_x", store="test", locator="t:1", text=text, value=text)


class TestExtract(unittest.TestCase):
    def test_test_outcome_pass(self):
        c = extract_claim(entry("Test suite: all tests pass"), set())
        self.assertEqual(c.claim_type, model.TEST_OUTCOME)
        self.assertEqual(c.params["expected"], "pass")

    def test_test_outcome_fail(self):
        c = extract_claim(entry("the tests are failing on main"), set())
        self.assertEqual(c.claim_type, model.TEST_OUTCOME)
        self.assertEqual(c.params["expected"], "fail")

    def test_dependency_pinned(self):
        c = extract_claim(entry("requests==2.31.0 is pinned"), set())
        self.assertEqual(c.claim_type, model.DEPENDENCY_VERSION)
        self.assertEqual(c.params["package"], "requests")
        self.assertEqual(c.params["version"], "2.31.0")

    def test_dependency_from_manifest_names(self):
        c = extract_claim(entry("Dependency requests: 2.31.0"), {"requests"})
        self.assertEqual(c.claim_type, model.DEPENDENCY_VERSION)
        self.assertEqual(c.params["package"], "requests")

    def test_git_branch(self):
        c = extract_claim(entry("the current branch is main"), set())
        self.assertEqual(c.claim_type, model.GIT_STATE)
        self.assertEqual(c.params, {"kind": "branch", "expected": "main"})

    def test_git_head(self):
        c = extract_claim(entry("HEAD is at 0123abc"), set())
        self.assertEqual(c.claim_type, model.GIT_STATE)
        self.assertEqual(c.params["kind"], "head")

    def test_git_worktree(self):
        c = extract_claim(entry("working tree is clean"), set())
        self.assertEqual(c.claim_type, model.GIT_STATE)
        self.assertEqual(c.params["expected"], "clean")

    def test_command_outcome(self):
        c = extract_claim(entry("`make build` exits 0"), set())
        self.assertEqual(c.claim_type, model.COMMAND_OUTCOME)
        self.assertEqual(c.params["command"], "make build")
        self.assertEqual(c.params["expected_exit"], 0)

    def test_symbol_keyword_after(self):
        c = extract_claim(entry("slugify helper: defined in src/util.py"), set())
        self.assertEqual(c.claim_type, model.SYMBOL_EXISTS)
        self.assertEqual(c.params["symbol"], "slugify")
        self.assertEqual(c.params["file"], "src/util.py")

    def test_symbol_keyword_before(self):
        c = extract_claim(entry("the function parse_config reads TOML"), set())
        self.assertEqual(c.claim_type, model.SYMBOL_EXISTS)
        self.assertEqual(c.params["symbol"], "parse_config")

    def test_file_exists(self):
        c = extract_claim(entry("the parser lives in src/parser.py"), set())
        self.assertEqual(c.claim_type, model.FILE_EXISTS)
        self.assertEqual(c.params["path"], "src/parser.py")
        self.assertTrue(c.params["expected_exists"])

    def test_file_deleted(self):
        c = extract_claim(entry("src/old_module.py was deleted"), set())
        self.assertEqual(c.claim_type, model.FILE_EXISTS)
        self.assertFalse(c.params["expected_exists"])

    def test_config_value(self):
        c = extract_claim(entry("the config setting MAX_RETRIES is 5"), set())
        self.assertEqual(c.claim_type, model.CONFIG_VALUE)
        self.assertEqual(c.params["key"], "MAX_RETRIES")
        self.assertEqual(c.params["value"], "5")

    def test_judgment(self):
        c = extract_claim(
            entry("Review style: the team prefers small, frequent pull requests"), set()
        )
        self.assertEqual(c.claim_type, model.JUDGMENT)


if __name__ == "__main__":
    unittest.main()
