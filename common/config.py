"""Environment-driven configuration shared by project processes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


SUPPORTED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


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
    """Validated settings shared by the runnable processes."""

    app_env: str
    log_level: str
    grpc_workers: int
    rpc_timeout_seconds: float
    stream_keepalive_seconds: float
    shutdown_grace_seconds: float
    session_ttl_seconds: int
    chat_node_id: str
    chat_endpoint: ServiceEndpoint
    chat_database_path: Path
    file_storage_path: Path
    max_file_size_bytes: int
    file_chunk_size_bytes: int
    allowed_file_types: tuple[str, ...]
    max_message_length: int
    presence_timeout_seconds: float
    llm_node_id: str
    llm_endpoint: ServiceEndpoint
    llm_adapter: str
    llm_model_path: Path
    llm_context_window: int
    llm_max_output_tokens: int
    llm_threads: int
    llm_gpu_layers: int
    llm_temperature: float
    llm_max_context_messages: int
    llm_max_context_chars: int
    llm_request_timeout_seconds: float
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


def _positive_int(source: Mapping[str, str], key: str, default: int) -> int:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{key} must be greater than zero")
    return value


def _positive_float(source: Mapping[str, str], key: str, default: float) -> float:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be a number") from exc
    if value <= 0:
        raise ConfigurationError(f"{key} must be greater than zero")
    return value


def _nonnegative_int(source: Mapping[str, str], key: str, default: int) -> int:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer") from exc
    if value < 0:
        raise ConfigurationError(f"{key} must not be negative")
    return value


def _nonnegative_float(source: Mapping[str, str], key: str, default: float) -> float:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be a number") from exc
    if value < 0:
        raise ConfigurationError(f"{key} must not be negative")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings from a supplied mapping or the local runtime environment.

    Normal application startup reads the repository-root ``.env`` file first.
    Existing process environment variables win over values in that file.
    Supplying ``environ`` bypasses ``.env`` loading, which keeps tests and
    programmatic callers deterministic.
    """

    if environ is None:
        load_dotenv(dotenv_path=DEFAULT_ENV_FILE, override=False)
        source: Mapping[str, str] = os.environ
    else:
        source = environ
    log_level = _required_text(source, "LOG_LEVEL", "INFO").upper()
    if log_level not in SUPPORTED_LOG_LEVELS:
        choices = ", ".join(sorted(SUPPORTED_LOG_LEVELS))
        raise ConfigurationError(f"LOG_LEVEL must be one of: {choices}")

    allowed_file_types = tuple(
        item.strip().lower()
        for item in source.get(
            "ALLOWED_FILE_TYPES",
            "text/plain,application/pdf,image/png,image/jpeg,application/octet-stream",
        ).split(",")
        if item.strip()
    )
    if not allowed_file_types:
        raise ConfigurationError("ALLOWED_FILE_TYPES must contain at least one value")

    llm_adapter = _required_text(source, "LLM_ADAPTER", "mock").lower()
    if llm_adapter not in {"mock", "local"}:
        raise ConfigurationError("LLM_ADAPTER must be 'mock' or 'local'")

    return Settings(
        app_env=_required_text(source, "APP_ENV", "development"),
        log_level=log_level,
        grpc_workers=_positive_int(source, "GRPC_WORKERS", 10),
        rpc_timeout_seconds=_positive_float(source, "RPC_TIMEOUT_SECONDS", 5.0),
        stream_keepalive_seconds=_positive_float(
            source, "STREAM_KEEPALIVE_SECONDS", 1.0
        ),
        shutdown_grace_seconds=_positive_float(
            source, "SHUTDOWN_GRACE_SECONDS", 5.0
        ),
        session_ttl_seconds=_positive_int(source, "SESSION_TTL_SECONDS", 3600),
        chat_node_id=_required_text(source, "CHAT_NODE_ID", "chat-node-1"),
        chat_endpoint=ServiceEndpoint(
            host=_required_text(source, "CHAT_HOST", "127.0.0.1"),
            port=_port(source, "CHAT_PORT", 50051),
        ),
        chat_database_path=Path(
            _required_text(source, "CHAT_DATABASE_PATH", "data/chat-node-1.db")
        ),
        file_storage_path=Path(
            _required_text(source, "FILE_STORAGE_PATH", "uploads/chat-node-1")
        ),
        max_file_size_bytes=_positive_int(source, "MAX_FILE_SIZE_BYTES", 10_485_760),
        file_chunk_size_bytes=_positive_int(source, "FILE_CHUNK_SIZE_BYTES", 65_536),
        allowed_file_types=allowed_file_types,
        max_message_length=_positive_int(source, "MAX_MESSAGE_LENGTH", 4_000),
        presence_timeout_seconds=_positive_float(
            source, "PRESENCE_TIMEOUT_SECONDS", 15.0
        ),
        llm_node_id=_required_text(source, "LLM_NODE_ID", "llm-node-1"),
        llm_endpoint=ServiceEndpoint(
            host=_required_text(source, "LLM_HOST", "127.0.0.1"),
            port=_port(source, "LLM_PORT", 50061),
        ),
        llm_adapter=llm_adapter,
        llm_model_path=Path(
            _required_text(
                source,
                "LLM_MODEL_PATH",
                "models/qwen2.5-3b-instruct-q4_k_m.gguf",
            )
        ),
        llm_context_window=_positive_int(source, "LLM_CONTEXT_WINDOW", 4096),
        llm_max_output_tokens=_positive_int(source, "LLM_MAX_OUTPUT_TOKENS", 256),
        llm_threads=_positive_int(source, "LLM_THREADS", 8),
        llm_gpu_layers=_nonnegative_int(source, "LLM_GPU_LAYERS", 0),
        llm_temperature=_nonnegative_float(source, "LLM_TEMPERATURE", 0.2),
        llm_max_context_messages=_positive_int(
            source, "LLM_MAX_CONTEXT_MESSAGES", 40
        ),
        llm_max_context_chars=_positive_int(source, "LLM_MAX_CONTEXT_CHARS", 12_000),
        llm_request_timeout_seconds=_positive_float(
            source, "LLM_REQUEST_TIMEOUT_SECONDS", 30.0
        ),
        client_id=_required_text(source, "CLIENT_ID", "client-1"),
    )
