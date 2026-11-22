import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))

import build_fixture
from memreckon.mcp_server import call_tool, handle_message


class TestMcpServer(unittest.TestCase):
    def test_initialize(self):
        reply = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(reply["result"]["serverInfo"]["name"], "memreckon")

    def test_tools_list(self):
        reply = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in reply["result"]["tools"]]
        self.assertEqual(names, ["audit_store", "gate_context", "verify_ledger"])

    def test_audit_tool_on_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_fixture.build(Path(tmp) / "fx")
            reply = handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "audit_store",
                        "arguments": {
                            "store_path": str(paths["markdown"]),
                            "repo_path": str(paths["repo"]),
                        },
                    },
                }
            )
            payload = reply["result"]["structuredContent"]
            counts = payload["counts"]
            self.assertEqual(counts["VERIFIED"], 1)
            self.assertEqual(counts["REFUTED"], 1)
            self.assertEqual(counts["STALE"], 1)
            self.assertEqual(counts["UNVERIFIABLE"], 1)

    def test_gate_tool_quarantines(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_fixture.build(Path(tmp) / "fx")
            payload = call_tool(
                "gate_context",
                {
                    "store_path": str(paths["memoryvault"]),
                    "repo_path": str(paths["repo"]),
                },
            )
            self.assertEqual(len(payload["quarantined"]), 1)
            self.assertIn("Test suite", payload["quarantined"][0]["text"])

    def test_unknown_tool_is_error_not_crash(self):
        reply = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
        self.assertTrue(reply["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
