from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PlaceholderProcessTests(unittest.TestCase):
    def test_each_process_reports_its_identity(self) -> None:
        expected = {
            "server": ("chat-server", "chat-node-1", 2, False),
            "llm_server": ("llm-server", "llm-node-1", 1, True),
            "client": ("chat-client", "client-1", 2, True),
        }
        for module_name, (service, node_id, phase, placeholder) in expected.items():
            with self.subTest(module=module_name):
                arguments = [sys.executable, "-m", module_name, "--once"]
                if module_name in {"server", "llm_server"}:
                    arguments.extend(("--bind", "127.0.0.1:0"))
                with tempfile.TemporaryDirectory() as directory:
                    environment = os.environ.copy()
                    environment["CHAT_DATABASE_PATH"] = str(
                        Path(directory) / "startup.db"
                    )
                    result = subprocess.run(
                        arguments,
                        cwd=PROJECT_ROOT,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                        env=environment,
                    )
                self.assertEqual(result.returncode, 0, result.stderr)
                line = result.stderr.strip().splitlines()[-1]
                payload = json.loads(line)
                self.assertEqual(payload["event"], "service_started")
                self.assertEqual(payload["service_name"], service)
                self.assertEqual(payload["service_node_id"], node_id)
                self.assertEqual(payload["placeholder"], placeholder)
                self.assertTrue(payload["skeleton"])
                self.assertEqual(payload["phase"], phase)


if __name__ == "__main__":
    unittest.main()
