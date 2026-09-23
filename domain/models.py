"""Initial data-only domain models for the approved project requirements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PresenceStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class User:
    id: str
    username: str
    role: UserRole
    status: UserStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.username, "username")
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.user_id, "user_id")
        _require_text(self.token_hash, "token_hash")
        _require_utc(self.created_at, "created_at")
        _require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.revoked_at is not None:
            _require_utc(self.revoked_at, "revoked_at")


@dataclass(frozen=True, slots=True)
class Channel:
    id: str
    name: str
    created_by: str
    created_at: datetime
    is_archived: bool = False

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.name, "name")
        _require_text(self.created_by, "created_by")
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ChannelMember:
    channel_id: str
    user_id: str
    joined_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.channel_id, "channel_id")
        _require_text(self.user_id, "user_id")
        _require_utc(self.joined_at, "joined_at")


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    channel_id: str
    sender_id: str
    body: str
    created_at: datetime
    client_request_id: str

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.channel_id, "channel_id")
        _require_text(self.sender_id, "sender_id")
        _require_text(self.body, "body")
        _require_text(self.client_request_id, "client_request_id")
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class FileMetadata:
    id: str
    channel_id: str
    uploader_id: str
    original_name: str
    storage_reference: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime
    message_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "channel_id",
            "uploader_id",
            "original_name",
            "storage_reference",
            "content_type",
            "checksum_sha256",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Presence:
    user_id: str
    status: PresenceStatus
    last_seen_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.user_id, "user_id")
        _require_utc(self.last_seen_at, "last_seen_at")


@dataclass(frozen=True, slots=True)
class ConversationContext:
    requester_id: str
    channel_id: str
    message_ids: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.requester_id, "requester_id")
        _require_text(self.channel_id, "channel_id")
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    occurred_at: datetime
    request_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "actor_id",
            "action",
            "target_type",
            "target_id",
            "request_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_utc(self.occurred_at, "occurred_at")

