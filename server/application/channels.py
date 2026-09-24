"""Authenticated channel lifecycle and membership logic."""

from __future__ import annotations

import base64
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from common.errors import ApplicationError, ErrorCode
from common.metadata import utc_now
from domain.models import Channel, ChannelMember, User, UserRole
from server.application.auth import AuthApplication
from server.application.commands import CreateChannelCommand
from server.repositories.sqlite import SQLiteUnitOfWorkFactory, is_unique_violation


@dataclass(frozen=True, slots=True)
class ChannelPage:
    channels: list[Channel]
    next_page_token: str


def _decode_page_token(token: str, request_id: str) -> int:
    if not token:
        return 0
    try:
        padding = "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        offset = int(decoded.decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ApplicationError(
            ErrorCode.INVALID_ARGUMENT, "page_token is invalid", request_id
        ) from exc
    if offset < 0:
        raise ApplicationError(
            ErrorCode.INVALID_ARGUMENT, "page_token is invalid", request_id
        )
    return offset


def _encode_page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


class ChannelApplication:
    def __init__(
        self,
        unit_of_work_factory: SQLiteUnitOfWorkFactory,
        auth: AuthApplication,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._auth = auth
        self._clock = clock

    def create_channel(
        self, token: str | None, name: str, *, request_id: str
    ) -> Channel:
        admin = self._auth.require_admin(token, request_id=request_id)
        normalized_name = name.strip()
        if not 1 <= len(normalized_name) <= 80:
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT,
                "channel name must contain 1-80 characters",
                request_id,
            )
        command = CreateChannelCommand(
            channel_id=str(uuid4()),
            name=normalized_name,
            creator_id=admin.id,
            created_at=self._clock(),
        )
        channel = Channel(
            id=command.channel_id,
            name=command.name,
            created_by=command.creator_id,
            created_at=command.created_at,
        )
        try:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.channels.add(channel)
                unit_of_work.channels.add_member(
                    ChannelMember(channel.id, admin.id, command.created_at)
                )
                unit_of_work.commit()
        except sqlite3.IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApplicationError(
                    ErrorCode.ALREADY_EXISTS, "channel name already exists", request_id
                ) from exc
            raise
        return channel

    def list_channels(
        self,
        token: str | None,
        page_size: int,
        page_token: str,
        *,
        request_id: str,
    ) -> ChannelPage:
        user = self._auth.authenticate(token, request_id=request_id)
        if page_size < 0 or page_size > 100:
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT,
                "page_size must be between 0 and 100",
                request_id,
            )
        limit = page_size or 50
        offset = _decode_page_token(page_token, request_id)
        with self._unit_of_work_factory() as unit_of_work:
            channels = unit_of_work.channels.list(
                include_archived=user.role is UserRole.ADMIN,
                limit=limit + 1,
                offset=offset,
            )
        has_more = len(channels) > limit
        visible = channels[:limit]
        return ChannelPage(
            visible, _encode_page_token(offset + limit) if has_more else ""
        )

    def join_channel(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> None:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            channel = self._active_channel(unit_of_work, channel_id, request_id)
            unit_of_work.channels.add_member(
                ChannelMember(channel.id, user.id, self._clock())
            )
            unit_of_work.commit()

    def leave_channel(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> None:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            self._active_channel(unit_of_work, channel_id, request_id)
            if not unit_of_work.channels.remove_member(channel_id, user.id):
                raise ApplicationError(
                    ErrorCode.PERMISSION_DENIED,
                    "user is not a member of the channel",
                    request_id,
                )
            unit_of_work.commit()

    def require_member(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> User:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            self._active_channel(unit_of_work, channel_id, request_id)
            if not unit_of_work.channels.is_member(channel_id, user.id):
                raise ApplicationError(
                    ErrorCode.PERMISSION_DENIED,
                    "channel membership required",
                    request_id,
                )
        return user

    @staticmethod
    def _active_channel(unit_of_work: object, channel_id: str, request_id: str) -> Channel:
        channel = unit_of_work.channels.get(channel_id)
        if channel is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
        if channel.is_archived:
            raise ApplicationError(
                ErrorCode.CONFLICT, "channel is archived", request_id
            )
        return channel

