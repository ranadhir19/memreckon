import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memreckon.ledger import LedgerWriter, read_verdicts, verify_ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_two(self):
        with LedgerWriter(self.path) as w:
            w.append("audit", {"store": "markdown"})
            w.append("verdict", {"verdict": {"stamp": "VERIFIED"}, "entry": {"id": "e_1"}})

    def test_chain_verifies(self):
        self._write_two()
        ok, problems = verify_ledger(self.path)
        self.assertTrue(ok, problems)

    def test_read_verdicts(self):
        self._write_two()
        verdicts = read_verdicts(self.path)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["verdict"]["stamp"], "VERIFIED")

    def test_append_continues_chain(self):
        self._write_two()
        with LedgerWriter(self.path) as w:
            w.append("summary", {"counts": {}})
        ok, problems = verify_ledger(self.path)
        self.assertTrue(ok, problems)
        seqs = [
            json.loads(line)["seq"]
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(seqs, [1, 2, 3])

    def test_tamper_detected(self):
        self._write_two()
        lines = self.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["payload"]["verdict"]["stamp"] = "REFUTED"  # rewrite history
        lines[1] = json.dumps(record)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, problems = verify_ledger(self.path)
        self.assertFalse(ok)
        self.assertTrue(any("altered" in p for p in problems))

    def test_deletion_detected(self):
        self._write_two()
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text(lines[0] + "\n", encoding="utf-8")
        # Chain still verifies for the remaining prefix -- but seq/hash of a
        # truncated tail is a different failure mode; here we check that
        # removing the FIRST record breaks the chain link of the second.
        lines2 = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines2), 1)
        self.path.write_text(lines[1] + "\n", encoding="utf-8")
        ok, _ = verify_ledger(self.path)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
