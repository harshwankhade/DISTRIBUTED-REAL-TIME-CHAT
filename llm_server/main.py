"""Runnable Phase 1 LLM gRPC service skeleton."""

from __future__ import annotations

import argparse

from common.config import ConfigurationError, load_settings
from common.logging import configure_logging
from llm_server.grpc_server import create_llm_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 1 LLM gRPC skeleton")
    parser.add_argument(
        "--once",
        action="store_true",
        help="bind, print service identity, then stop instead of waiting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    logger = configure_logging(
        service="llm-server",
        node_id=settings.llm_node_id,
        level=settings.log_level,
    )
    server, bound_address = create_llm_server(settings, logger=logger)
    server.start()
    logger.info(
        "service_started",
        extra={
            "phase": 1,
            "skeleton": True,
            "placeholder": True,
            "service_name": "llm-server",
            "service_node_id": settings.llm_node_id,
            "listen_address": bound_address,
        },
    )
    if args.once:
        server.stop(0).wait()
        return 0
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("service_stopping", extra={"grace_seconds": settings.shutdown_grace_seconds})
        server.stop(settings.shutdown_grace_seconds).wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
