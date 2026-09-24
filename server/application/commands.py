"""Deterministic durable command inputs created before persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.models import UserRole, UserStatus


@dataclass(frozen=True, slots=True)
class CreateUserCommand:
    user_id: str
    username: str
    password_hash: str
    role: UserRole
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SetUserStatusCommand:
    user_id: str
    status: UserStatus
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class SetUserRoleCommand:
    user_id: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class CreateChannelCommand:
    channel_id: str
    name: str
    creator_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ArchiveChannelCommand:
    channel_id: str
    archived_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeMembershipCommand:
    channel_id: str
    user_id: str
    add: bool
    changed_at: datetime

