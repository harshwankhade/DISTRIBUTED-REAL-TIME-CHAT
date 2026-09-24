"""SQLite repository adapters and transaction boundary."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

from domain.models import Channel, ChannelMember, Session, User, UserRole, UserStatus
from server.database import Database


def _to_text(value: datetime) -> str:
    return value.isoformat()


def _from_text(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class StoredUser:
    user: User
    password_hash: str


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        role=UserRole(row["role"]),
        status=UserStatus(row["status"]),
        created_at=_from_text(row["created_at"]),
    )


def _channel_from_row(row: sqlite3.Row) -> Channel:
    return Channel(
        id=row["id"],
        name=row["name"],
        created_by=row["created_by"],
        created_at=_from_text(row["created_at"]),
        is_archived=row["archived_at"] is not None,
    )


class SQLiteUserRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, user: User, password_hash: str) -> None:
        self._connection.execute(
            """
            INSERT INTO users(id, username, password_hash, role, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username,
                password_hash,
                user.role.value,
                user.status.value,
                _to_text(user.created_at),
            ),
        )

    def get(self, user_id: str) -> StoredUser | None:
        row = self._connection.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return None if row is None else StoredUser(_user_from_row(row), row["password_hash"])

    def get_by_username(self, username: str) -> StoredUser | None:
        row = self._connection.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        return None if row is None else StoredUser(_user_from_row(row), row["password_hash"])

    def set_status(self, user_id: str, status: UserStatus) -> User | None:
        cursor = self._connection.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status.value, user_id)
        )
        if cursor.rowcount == 0:
            return None
        stored = self.get(user_id)
        return None if stored is None else stored.user

    def set_role(self, user_id: str, role: UserRole) -> User | None:
        cursor = self._connection.execute(
            "UPDATE users SET role = ? WHERE id = ?", (role.value, user_id)
        )
        if cursor.rowcount == 0:
            return None
        stored = self.get(user_id)
        return None if stored is None else stored.user


class SQLiteSessionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, session: Session) -> None:
        self._connection.execute(
            """
            INSERT INTO sessions(id, user_id, token_hash, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.user_id,
                session.token_hash,
                _to_text(session.created_at),
                _to_text(session.expires_at),
                None if session.revoked_at is None else _to_text(session.revoked_at),
            ),
        )

    def get_by_token_hash(self, token_hash: str) -> Session | None:
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=_from_text(row["created_at"]),
            expires_at=_from_text(row["expires_at"]),
            revoked_at=None if row["revoked_at"] is None else _from_text(row["revoked_at"]),
        )

    def revoke(self, token_hash: str, revoked_at: datetime) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE sessions SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (_to_text(revoked_at), token_hash),
        )
        return cursor.rowcount > 0

    def revoke_for_user(self, user_id: str, revoked_at: datetime) -> int:
        cursor = self._connection.execute(
            """
            UPDATE sessions SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (_to_text(revoked_at), user_id),
        )
        return cursor.rowcount


class SQLiteChannelRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, channel: Channel) -> None:
        self._connection.execute(
            """
            INSERT INTO channels(id, name, created_by, created_at, archived_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (channel.id, channel.name, channel.created_by, _to_text(channel.created_at)),
        )

    def get(self, channel_id: str) -> Channel | None:
        row = self._connection.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return None if row is None else _channel_from_row(row)

    def list(self, *, include_archived: bool, limit: int, offset: int) -> list[Channel]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        rows = self._connection.execute(
            f"SELECT * FROM channels {where} ORDER BY name, id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_channel_from_row(row) for row in rows]

    def archive(self, channel_id: str, archived_at: datetime) -> Channel | None:
        cursor = self._connection.execute(
            """
            UPDATE channels SET archived_at = ?
            WHERE id = ? AND archived_at IS NULL
            """,
            (_to_text(archived_at), channel_id),
        )
        if cursor.rowcount == 0:
            return self.get(channel_id)
        return self.get(channel_id)

    def add_member(self, member: ChannelMember) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO channel_members(channel_id, user_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (member.channel_id, member.user_id, _to_text(member.joined_at)),
        )
        return cursor.rowcount > 0

    def remove_member(self, channel_id: str, user_id: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM channel_members WHERE channel_id = ? AND user_id = ?",
            (channel_id, user_id),
        )
        return cursor.rowcount > 0

    def is_member(self, channel_id: str, user_id: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM channel_members WHERE channel_id = ? AND user_id = ?
            """,
            (channel_id, user_id),
        ).fetchone()
        return row is not None


class SQLiteUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._database = database
        self.connection: sqlite3.Connection | None = None
        self.users: SQLiteUserRepository
        self.sessions: SQLiteSessionRepository
        self.channels: SQLiteChannelRepository
        self._committed = False

    def __enter__(self) -> SQLiteUnitOfWork:
        self.connection = self._database.connect()
        self.connection.execute("BEGIN")
        self.users = SQLiteUserRepository(self.connection)
        self.sessions = SQLiteSessionRepository(self.connection)
        self.channels = SQLiteChannelRepository(self.connection)
        return self

    def commit(self) -> None:
        if self.connection is None:
            raise RuntimeError("unit of work is not active")
        self.connection.commit()
        self._committed = True

    def rollback(self) -> None:
        if self.connection is not None:
            self.connection.rollback()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.connection is None:
            return
        if exc_type is not None or not self._committed:
            self.connection.rollback()
        self.connection.close()
        self.connection = None


class SQLiteUnitOfWorkFactory:
    def __init__(self, database: Database) -> None:
        self._database = database

    def __call__(self) -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(self._database)


def is_unique_violation(error: sqlite3.IntegrityError) -> bool:
    return "UNIQUE constraint failed" in str(error)

