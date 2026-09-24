from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.config import ConfigurationError, load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        settings = load_settings({})
        self.assertEqual(settings.chat_endpoint.address, "127.0.0.1:50051")
        self.assertEqual(settings.llm_endpoint.address, "127.0.0.1:50061")
        self.assertEqual(settings.chat_node_id, "chat-node-1")

    def test_environment_overrides_defaults(self) -> None:
        settings = load_settings(
            {
                "CHAT_HOST": "0.0.0.0",
                "CHAT_PORT": "55001",
                "CHAT_NODE_ID": "chat-a",
                "LOG_LEVEL": "debug",
            }
        )
        self.assertEqual(settings.chat_endpoint.address, "0.0.0.0:55001")
        self.assertEqual(settings.chat_node_id, "chat-a")
        self.assertEqual(settings.log_level, "DEBUG")

    def test_dotenv_is_loaded_from_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text(
                "CHAT_NODE_ID=chat-from-dotenv\nCHAT_PORT=55123\n",
                encoding="utf-8",
            )
            with (
                patch("common.config.DEFAULT_ENV_FILE", env_file),
                patch.dict(os.environ, {}, clear=True),
            ):
                settings = load_settings()

        self.assertEqual(settings.chat_node_id, "chat-from-dotenv")
        self.assertEqual(settings.chat_endpoint.port, 55123)

    def test_process_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text("CHAT_NODE_ID=chat-from-dotenv\n", encoding="utf-8")
            with (
                patch("common.config.DEFAULT_ENV_FILE", env_file),
                patch.dict(
                    os.environ,
                    {"CHAT_NODE_ID": "chat-from-process"},
                    clear=True,
                ),
            ):
                settings = load_settings()

        self.assertEqual(settings.chat_node_id, "chat-from-process")

    def test_invalid_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "CHAT_PORT"):
            load_settings({"CHAT_PORT": "70000"})

    def test_invalid_log_level_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "LOG_LEVEL"):
            load_settings({"LOG_LEVEL": "verbose"})

    def test_invalid_session_ttl_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "SESSION_TTL_SECONDS"):
            load_settings({"SESSION_TTL_SECONDS": "0"})


if __name__ == "__main__":
    unittest.main()
