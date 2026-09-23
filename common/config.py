"""Environment-driven configuration for the Phase 0 processes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigurationError(ValueError):
    """Raised when runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ServiceEndpoint:
    """Network identity that will later be used by a gRPC service."""

    host: str
    port: int

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by the placeholder processes."""

    app_env: str
    log_level: str
    chat_node_id: str
    chat_endpoint: ServiceEndpoint
    chat_database_path: Path
    llm_node_id: str
    llm_endpoint: ServiceEndpoint
    client_id: str


def _required_text(source: Mapping[str, str], key: str, default: str) -> str:
    value = source.get(key, default).strip()
    if not value:
        raise ConfigurationError(f"{key} must not be empty")
    return value


def _port(source: Mapping[str, str], key: str, default: int) -> int:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ConfigurationError(f"{key} must be between 1 and 65535")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings from a supplied mapping or the process environment."""

    source = os.environ if environ is None else environ
    log_level = _required_text(source, "LOG_LEVEL", "INFO").upper()
    if log_level not in SUPPORTED_LOG_LEVELS:
        choices = ", ".join(sorted(SUPPORTED_LOG_LEVELS))
        raise ConfigurationError(f"LOG_LEVEL must be one of: {choices}")

    return Settings(
        app_env=_required_text(source, "APP_ENV", "development"),
        log_level=log_level,
        chat_node_id=_required_text(source, "CHAT_NODE_ID", "chat-node-1"),
        chat_endpoint=ServiceEndpoint(
            host=_required_text(source, "CHAT_HOST", "127.0.0.1"),
            port=_port(source, "CHAT_PORT", 50051),
        ),
        chat_database_path=Path(
            _required_text(source, "CHAT_DATABASE_PATH", "data/chat-node-1.db")
        ),
        llm_node_id=_required_text(source, "LLM_NODE_ID", "llm-node-1"),
        llm_endpoint=ServiceEndpoint(
            host=_required_text(source, "LLM_HOST", "127.0.0.1"),
            port=_port(source, "LLM_PORT", 50061),
        ),
        client_id=_required_text(source, "CLIENT_ID", "client-1"),
    )

