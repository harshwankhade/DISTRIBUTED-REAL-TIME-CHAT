from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PlaceholderProcessTests(unittest.TestCase):
    def test_each_process_reports_its_identity(self) -> None:
        expected = {
            "server": ("chat-server", "chat-node-1"),
            "llm_server": ("llm-server", "llm-node-1"),
            "client": ("chat-client", "client-1"),
        }
        for module_name, (service, node_id) in expected.items():
            with self.subTest(module=module_name):
                result = subprocess.run(
                    [sys.executable, "-m", module_name, "--once"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                line = result.stderr.strip().splitlines()[-1]
                payload = json.loads(line)
                self.assertEqual(payload["event"], "service_started")
                self.assertEqual(payload["service_name"], service)
                self.assertEqual(payload["service_node_id"], node_id)
                self.assertTrue(payload["placeholder"])


if __name__ == "__main__":
    unittest.main()
