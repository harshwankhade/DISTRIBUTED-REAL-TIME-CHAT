"""Request identifiers and timestamp helpers used at process boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_request_id() -> str:
    """Create an opaque correlation ID at the request boundary."""

    return str(uuid4())


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)

