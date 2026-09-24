"""Runnable client identity and Phase 1 gRPC smoke test."""

from __future__ import annotations

import argparse
import os

from common.config import ConfigurationError, load_settings
from common.logging import configure_logging
from common.runtime import announce_placeholder
from client.grpc_client import run_smoke_test


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 1 chat client skeleton")
    parser.add_argument(
        "--once",
        action="store_true",
        help="accepted for consistency; the placeholder client exits after startup",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="call health/login/stream skeletons on the configured chat server",
    )
    parser.add_argument(
        "--target",
        help="override the configured chat server address for the smoke test",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    logger = configure_logging(
        service="chat-client",
        node_id=settings.client_id,
        level=settings.log_level,
    )
    target = args.target or settings.chat_endpoint.address
    if args.smoke:
        username = os.environ.get("SMOKE_USERNAME", "").strip()
        password = os.environ.get("SMOKE_PASSWORD", "")
        if not username or not password:
            raise SystemExit(
                "SMOKE_USERNAME and SMOKE_PASSWORD are required for --smoke"
            )
        result = run_smoke_test(
            target=target,
            timeout_seconds=settings.rpc_timeout_seconds,
            username=username,
            password=password,
        )
        logger.info(
            "smoke_test_completed",
            extra={
                "phase": 2,
                "target": target,
                "health_serving": result.health_serving,
                "health_request_id": result.health_request_id,
                "login_status": result.login_status,
                "stream_event_type": result.stream_event_type,
                "stream_cancelled": result.stream_cancelled,
            },
        )
        passed = (
            result.health_serving
            and result.login_status == "OK"
            and result.stream_event_type == "CHAT_EVENT_TYPE_KEEPALIVE"
            and result.stream_cancelled
        )
        return 0 if passed else 1

    announce_placeholder(
        logger,
        service="chat-client",
        node_id=settings.client_id,
        address=target,
        once=True,
        phase=2,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
