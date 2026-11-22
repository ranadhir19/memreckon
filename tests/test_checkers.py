import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memreckon import checkers, model
from memreckon.checkers import CheckContext
from memreckon.model import Claim


def claim(claim_type, **params):
    return Claim(entry_id="e_x", claim_type=claim_type, params=params)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        self.ctx = CheckContext(repo=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


class TestFileExists(RepoCase):
    def test_present(self):
        self.write("src/app.py", "x = 1\n")
        raw = checkers.check_file_exists(claim(model.FILE_EXISTS, path="src/app.py"), self.ctx)
        self.assertEqual(raw.outcome, "pass")

    def test_absent(self):
        raw = checkers.check_file_exists(claim(model.FILE_EXISTS, path="src/gone.py"), self.ctx)
        self.assertEqual(raw.outcome, "fail")

    def test_expected_absent(self):
        raw = checkers.check_file_exists(
            claim(model.FILE_EXISTS, path="src/gone.py", expected_exists=False), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")


class TestSymbol(RepoCase):
    def test_definition_found(self):
        self.write("src/util.py", "def slugify(t):\n    return t\n")
        raw = checkers.check_symbol_exists(
            claim(model.SYMBOL_EXISTS, symbol="slugify", file="src/util.py"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")
        self.assertEqual(raw.evidence["match_kind"], "definition")

    def test_absent(self):
        self.write("src/util.py", "def other(t):\n    return t\n")
        raw = checkers.check_symbol_exists(
            claim(model.SYMBOL_EXISTS, symbol="slugify"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")

    def test_named_file_missing(self):
        raw = checkers.check_symbol_exists(
            claim(model.SYMBOL_EXISTS, symbol="slugify", file="src/nope.py"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")


class TestDependency(RepoCase):
    def setUp(self):
        super().setUp()
        self.write("requirements.txt", "requests==2.31.0\nflask>=3.0\n")

    def test_exact_match(self):
        raw = checkers.check_dependency_version(
            claim(model.DEPENDENCY_VERSION, package="requests", version="2.31.0"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")

    def test_version_mismatch(self):
        raw = checkers.check_dependency_version(
            claim(model.DEPENDENCY_VERSION, package="requests", version="9.9.9"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")

    def test_range_satisfied(self):
        raw = checkers.check_dependency_version(
            claim(model.DEPENDENCY_VERSION, package="flask", version="3.0.1"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")

    def test_package_absent_is_refuted(self):
        raw = checkers.check_dependency_version(
            claim(model.DEPENDENCY_VERSION, package="numpy", version="1.26.0"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")


class TestConfig(RepoCase):
    def test_env_value_match(self):
        self.write(".env", "MAX_RETRIES=5\n")
        raw = checkers.check_config_value(
            claim(model.CONFIG_VALUE, key="MAX_RETRIES", value="5"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")

    def test_env_value_mismatch(self):
        self.write(".env", "MAX_RETRIES=5\n")
        raw = checkers.check_config_value(
            claim(model.CONFIG_VALUE, key="MAX_RETRIES", value="3"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")

    def test_key_missing_is_unverifiable_not_refuted(self):
        raw = checkers.check_config_value(
            claim(model.CONFIG_VALUE, key="NOPE_KEY", value="1"), self.ctx
        )
        self.assertEqual(raw.outcome, "unable")
        self.assertEqual(raw.reason, model.R_KEY_NOT_FOUND)


class TestGit(RepoCase):
    def test_not_a_repo(self):
        raw = checkers.check_git_state(
            claim(model.GIT_STATE, kind="branch", expected="main"), self.ctx
        )
        self.assertEqual(raw.outcome, "unable")
        self.assertEqual(raw.reason, model.R_NOT_A_GIT_REPO)

    def test_branch_and_worktree(self):
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)
        self.write("a.txt", "a\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.repo, check=True)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        raw = checkers.check_git_state(
            claim(model.GIT_STATE, kind="branch", expected=branch), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")
        raw = checkers.check_git_state(
            claim(model.GIT_STATE, kind="branch", expected="no-such-branch"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")
        raw = checkers.check_git_state(
            claim(model.GIT_STATE, kind="worktree", expected="clean"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass")
        self.write("b.txt", "b\n")
        raw = checkers.check_git_state(
            claim(model.GIT_STATE, kind="worktree", expected="clean"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail")


class TestCommand(RepoCase):
    def test_disabled_by_default(self):
        raw = checkers.check_command_outcome(
            claim(model.COMMAND_OUTCOME, command="true", expected_exit=0), self.ctx
        )
        self.assertEqual(raw.outcome, "unable")
        self.assertEqual(raw.reason, model.R_COMMANDS_DISABLED)

    def test_opt_in_runs(self):
        ctx = CheckContext(repo=self.repo, run_commands=True)
        cmd = f'"{sys.executable}" -c "pass"'
        raw = checkers.check_command_outcome(
            claim(model.COMMAND_OUTCOME, command=cmd, expected_exit=0), ctx
        )
        self.assertEqual(raw.outcome, "pass")
        raw = checkers.check_command_outcome(
            claim(model.COMMAND_OUTCOME, command=cmd, expected_exit=1), ctx
        )
        self.assertEqual(raw.outcome, "fail")


class TestTestOutcome(RepoCase):
    PASSING = (
        "import unittest\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertTrue(True)\n"
    )
    FAILING = (
        "import unittest\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_bad(self):\n"
        "        self.assertTrue(False)\n"
    )

    def test_passing_suite(self):
        self.write("tests/test_ok.py", self.PASSING)
        raw = checkers.check_test_outcome(
            claim(model.TEST_OUTCOME, expected="pass"), self.ctx
        )
        self.assertEqual(raw.outcome, "pass", raw.evidence)

    def test_failing_suite_refutes_pass_claim(self):
        self.write("tests/test_bad.py", self.FAILING)
        raw = checkers.check_test_outcome(
            claim(model.TEST_OUTCOME, expected="pass"), self.ctx
        )
        self.assertEqual(raw.outcome, "fail", raw.evidence)

    def test_no_suite_unverifiable(self):
        raw = checkers.check_test_outcome(
            claim(model.TEST_OUTCOME, expected="pass"), self.ctx
        )
        self.assertEqual(raw.outcome, "unable")
        self.assertEqual(raw.reason, model.R_NO_TEST_SUITE)


if __name__ == "__main__":
    unittest.main()
