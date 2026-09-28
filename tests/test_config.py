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

    def test_phase3_limits_and_file_types_are_configurable(self) -> None:
        settings = load_settings(
            {
                "MAX_FILE_SIZE_BYTES": "2048",
                "FILE_CHUNK_SIZE_BYTES": "128",
                "MAX_MESSAGE_LENGTH": "500",
                "PRESENCE_TIMEOUT_SECONDS": "2.5",
                "ALLOWED_FILE_TYPES": "text/plain, image/png",
            }
        )
        self.assertEqual(settings.max_file_size_bytes, 2048)
        self.assertEqual(settings.file_chunk_size_bytes, 128)
        self.assertEqual(settings.max_message_length, 500)
        self.assertEqual(settings.presence_timeout_seconds, 2.5)
        self.assertEqual(settings.allowed_file_types, ("text/plain", "image/png"))

    def test_empty_allowed_file_types_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "ALLOWED_FILE_TYPES"):
            load_settings({"ALLOWED_FILE_TYPES": " , "})

    def test_phase4_llm_settings_are_configurable(self) -> None:
        settings = load_settings(
            {
                "LLM_ADAPTER": "local",
                "LLM_CONTEXT_WINDOW": "2048",
                "LLM_MAX_OUTPUT_TOKENS": "128",
                "LLM_THREADS": "6",
                "LLM_GPU_LAYERS": "0",
                "LLM_TEMPERATURE": "0.1",
                "LLM_MAX_CONTEXT_MESSAGES": "12",
                "LLM_MAX_CONTEXT_CHARS": "4096",
                "LLM_REQUEST_TIMEOUT_SECONDS": "9",
            }
        )
        self.assertEqual(settings.llm_adapter, "local")
        self.assertEqual(settings.llm_context_window, 2048)
        self.assertEqual(settings.llm_max_output_tokens, 128)
        self.assertEqual(settings.llm_threads, 6)
        self.assertEqual(settings.llm_gpu_layers, 0)
        self.assertEqual(settings.llm_temperature, 0.1)
        self.assertEqual(settings.llm_max_context_messages, 12)
        self.assertEqual(settings.llm_max_context_chars, 4096)
        self.assertEqual(settings.llm_request_timeout_seconds, 9)

    def test_invalid_llm_adapter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "LLM_ADAPTER"):
            load_settings({"LLM_ADAPTER": "cloud"})


if __name__ == "__main__":
    unittest.main()
