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
from domain.models import Channel, ChannelMember, User
from server.application.auth import AuthApplication
from server.application.commands import CreateChannelCommand, DeleteChannelCommand
from server.repositories.sqlite import SQLiteUnitOfWorkFactory, is_unique_violation


@dataclass(frozen=True, slots=True)
class ChannelPage:
    channels: list[Channel]
    next_page_token: str
    memberships: frozenset[str] = frozenset()


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
        creator = self._auth.authenticate(token, request_id=request_id)
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
            creator_id=creator.id,
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
                    ChannelMember(channel.id, creator.id, command.created_at)
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
                include_archived=False,
                limit=limit + 1,
                offset=offset,
            )
            visible = channels[:limit]
            memberships = frozenset(
                channel.id for channel in visible
                if unit_of_work.channels.is_member(channel.id, user.id)
            )
        has_more = len(channels) > limit
        return ChannelPage(
            visible, _encode_page_token(offset + limit) if has_more else "",
            memberships,
        )

    def join_channel(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> None:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory(immediate=True) as unit_of_work:
            channel = self._active_channel(unit_of_work, channel_id, request_id)
            if unit_of_work.channels.is_member(channel_id, user.id):
                return
            unit_of_work.channels.request_join(
                str(uuid4()), channel.id, user.id, self._clock()
            )
            unit_of_work.commit()

    def leave_channel(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> None:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            channel = self._active_channel(unit_of_work, channel_id, request_id)
            if channel.created_by == user.id:
                raise ApplicationError(ErrorCode.CONFLICT, "channel owner cannot leave", request_id)
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

    def _require_owner(self, unit_of_work, channel_id: str, user_id: str,
                       request_id: str) -> Channel:
        channel = self._active_channel(unit_of_work, channel_id, request_id)
        if channel.created_by != user_id:
            raise ApplicationError(ErrorCode.PERMISSION_DENIED, "channel owner required", request_id)
        return channel

    def list_join_requests(self, token: str | None, channel_id: str,
                           *, request_id: str) -> list[tuple[str, User]]:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            self._require_owner(unit_of_work, channel_id, user.id, request_id)
            return unit_of_work.channels.list_join_requests(channel_id)

    def decide_join_request(self, token: str | None, join_id: str, approve: bool,
                            *, request_id: str) -> None:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory(immediate=True) as unit_of_work:
            pending = unit_of_work.channels.get_join_request(join_id)
            if pending is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "join request not found", request_id)
            self._require_owner(unit_of_work, pending["channel_id"], user.id, request_id)
            if pending["status"] != "pending":
                if pending["status"] == ("approved" if approve else "rejected"):
                    return
                raise ApplicationError(ErrorCode.CONFLICT, "join request already decided", request_id)
            if approve:
                target = unit_of_work.users.get(pending["user_id"])
                if target is None or target.user.status.value != "active":
                    raise ApplicationError(ErrorCode.CONFLICT, "requesting user is not active", request_id)
                unit_of_work.channels.add_member(
                    ChannelMember(pending["channel_id"], pending["user_id"], self._clock())
                )
            unit_of_work.channels.decide_join_request(join_id, approve, self._clock())
            unit_of_work.commit()

    def manage_member(self, token: str | None, channel_id: str, user_id: str,
                      add: bool, *, request_id: str) -> None:
        owner = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory(immediate=True) as unit_of_work:
            channel = self._require_owner(unit_of_work, channel_id, owner.id, request_id)
            target = unit_of_work.users.get(user_id)
            if target is None or target.user.status.value != "active":
                raise ApplicationError(ErrorCode.NOT_FOUND, "active user not found", request_id)
            if not add and user_id == channel.created_by:
                raise ApplicationError(ErrorCode.CONFLICT, "cannot remove channel owner", request_id)
            if add:
                unit_of_work.channels.add_member(ChannelMember(channel_id, user_id, self._clock()))
            else:
                unit_of_work.channels.remove_member(channel_id, user_id)
            unit_of_work.commit()

    def list_members(self, token: str | None, channel_id: str,
                     *, request_id: str) -> list[User]:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._unit_of_work_factory() as unit_of_work:
            self._active_channel(unit_of_work, channel_id, request_id)
            if not unit_of_work.channels.is_member(channel_id, user.id):
                raise ApplicationError(ErrorCode.PERMISSION_DENIED, "channel membership required", request_id)
            return unit_of_work.channels.list_members(channel_id)

    def delete_channel(self, token: str | None, channel_id: str,
                       *, request_id: str) -> None:
        owner = self._auth.authenticate(token, request_id=request_id)
        command = DeleteChannelCommand(channel_id=channel_id, owner_id=owner.id)
        with self._unit_of_work_factory(immediate=True) as unit_of_work:
            self._require_owner(unit_of_work, command.channel_id, command.owner_id, request_id)
            if not unit_of_work.channels.delete(command.channel_id):
                raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
            unit_of_work.commit()

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
