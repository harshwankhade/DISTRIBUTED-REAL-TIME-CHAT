"""Runnable Phase 0 placeholder for the future chat gRPC server."""

from __future__ import annotations

import argparse

from common.config import ConfigurationError, load_settings
from common.logging import configure_logging
from common.runtime import announce_placeholder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 0 chat server placeholder")
    parser.add_argument(
        "--once",
        action="store_true",
        help="print service identity and exit instead of waiting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    logger = configure_logging(
        service="chat-server",
        node_id=settings.chat_node_id,
        level=settings.log_level,
    )
    announce_placeholder(
        logger,
        service="chat-server",
        node_id=settings.chat_node_id,
        address=settings.chat_endpoint.address,
        once=args.once,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

