"""Administrator-only user and membership application logic."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from common.errors import ApplicationError, ErrorCode
from common.metadata import utc_now
from domain.models import Channel, ChannelMember, User, UserRole, UserStatus
from server.application.auth import AuthApplication
from server.application.commands import (
    ArchiveChannelCommand,
    ChangeMembershipCommand,
    CreateUserCommand,
    SetUserRoleCommand,
    SetUserStatusCommand,
)
from server.repositories.sqlite import SQLiteUnitOfWorkFactory, is_unique_violation
from server.security.passwords import hash_password


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class AdminApplication:
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

    def create_user(
        self,
        token: str | None,
        username: str,
        password: str,
        role: str,
        *,
        request_id: str,
    ) -> User:
        self._auth.require_admin(token, request_id=request_id)
        normalized_username = username.strip()
        if not USERNAME_PATTERN.fullmatch(normalized_username):
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT,
                "username must be 3-64 letters, numbers, dots, underscores, or hyphens",
                request_id,
            )
        try:
            user_role = UserRole(role.lower())
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, str(exc), request_id) from exc

        command = CreateUserCommand(
            user_id=str(uuid4()),
            username=normalized_username,
            password_hash=password_hash,
            role=user_role,
            created_at=self._clock(),
        )
        user = User(
            id=command.user_id,
            username=command.username,
            role=command.role,
            status=UserStatus.ACTIVE,
            created_at=command.created_at,
        )
        try:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.users.add(user, command.password_hash)
                unit_of_work.commit()
        except sqlite3.IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApplicationError(
                    ErrorCode.ALREADY_EXISTS, "username already exists", request_id
                ) from exc
            raise
        return user

    def set_user_status(
        self,
        token: str | None,
        user_id: str,
        status: str,
        *,
        request_id: str,
    ) -> User:
        self._auth.require_admin(token, request_id=request_id)
        try:
            user_status = UserStatus(status.lower())
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT, "status must be active or disabled", request_id
            ) from exc
        command = SetUserStatusCommand(user_id, user_status, self._clock())
        with self._unit_of_work_factory() as unit_of_work:
            user = unit_of_work.users.set_status(command.user_id, command.status)
            if user is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "user not found", request_id)
            if command.status is UserStatus.DISABLED:
                unit_of_work.sessions.revoke_for_user(user.id, command.changed_at)
            unit_of_work.commit()
            return user

    def set_user_role(
        self,
        token: str | None,
        user_id: str,
        role: str,
        *,
        request_id: str,
    ) -> User:
        self._auth.require_admin(token, request_id=request_id)
        try:
            user_role = UserRole(role.lower())
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT, "role must be user or admin", request_id
            ) from exc
        command = SetUserRoleCommand(user_id, user_role)
        with self._unit_of_work_factory() as unit_of_work:
            user = unit_of_work.users.set_role(command.user_id, command.role)
            if user is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "user not found", request_id)
            unit_of_work.commit()
            return user

    def archive_channel(
        self, token: str | None, channel_id: str, *, request_id: str
    ) -> Channel:
        self._auth.require_admin(token, request_id=request_id)
        command = ArchiveChannelCommand(channel_id, self._clock())
        with self._unit_of_work_factory() as unit_of_work:
            channel = unit_of_work.channels.archive(
                command.channel_id, command.archived_at
            )
            if channel is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
            unit_of_work.commit()
            return channel

    def manage_member(
        self,
        token: str | None,
        channel_id: str,
        user_id: str,
        add: bool,
        *,
        request_id: str,
    ) -> None:
        self._auth.require_admin(token, request_id=request_id)
        command = ChangeMembershipCommand(
            channel_id=channel_id,
            user_id=user_id,
            add=add,
            changed_at=self._clock(),
        )
        with self._unit_of_work_factory() as unit_of_work:
            channel = unit_of_work.channels.get(command.channel_id)
            if channel is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
            if channel.is_archived:
                raise ApplicationError(
                    ErrorCode.CONFLICT, "archived channel cannot change members", request_id
                )
            if unit_of_work.users.get(command.user_id) is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "user not found", request_id)
            if command.add:
                unit_of_work.channels.add_member(
                    ChannelMember(command.channel_id, command.user_id, command.changed_at)
                )
            elif not unit_of_work.channels.remove_member(
                command.channel_id, command.user_id
            ):
                raise ApplicationError(
                    ErrorCode.NOT_FOUND, "channel membership not found", request_id
                )
            unit_of_work.commit()

