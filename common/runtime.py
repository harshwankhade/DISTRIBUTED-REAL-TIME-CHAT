"""Runtime helpers for Phase 0 placeholder processes."""

from __future__ import annotations

import time
from logging import LoggerAdapter


def announce_placeholder(
    logger: LoggerAdapter,
    *,
    service: str,
    node_id: str,
    address: str | None,
    once: bool,
) -> None:
    """Announce process identity and optionally wait until interrupted."""

    logger.info(
        "service_started",
        extra={
            "phase": 0,
            "placeholder": True,
            "service_name": service,
            "service_node_id": node_id,
            "listen_address": address,
        },
    )
    if once:
        return

    logger.info(
        "placeholder_waiting",
        extra={"detail": "No network service is implemented in Phase 0"},
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("service_stopped", extra={"reason": "keyboard_interrupt"})

