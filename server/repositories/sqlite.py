"""SQLite repository adapters and transaction boundary."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

from domain.models import (
    Channel,
    ChannelMember,
    FileMetadata,
    Message,
    Session,
    User,
    UserRole,
    UserStatus,
)
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


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        channel_id=row["channel_id"],
        sender_id=row["sender_id"],
        body=row["body"],
        created_at=_from_text(row["created_at"]),
        client_request_id=row["client_request_id"],
        sender_username=row["sender_username"],
    )


def _file_from_row(row: sqlite3.Row) -> FileMetadata:
    return FileMetadata(
        id=row["id"],
        channel_id=row["channel_id"],
        uploader_id=row["uploader_id"],
        original_name=row["original_name"],
        storage_reference=row["storage_reference"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        checksum_sha256=row["checksum_sha256"],
        created_at=_from_text(row["created_at"]),
        message_id=row["message_id"],
        uploader_username=row["uploader_username"],
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


class SQLiteMessageRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, message: Message) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO messages(
                id, channel_id, sender_id, body, created_at, client_request_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.channel_id,
                message.sender_id,
                message.body,
                _to_text(message.created_at),
                message.client_request_id,
            ),
        )
        return cursor.rowcount > 0

    def get(self, message_id: str) -> Message | None:
        row = self._connection.execute(
            """SELECT messages.*, users.username AS sender_username
               FROM messages JOIN users ON users.id = messages.sender_id
               WHERE messages.id = ?""",
            (message_id,),
        ).fetchone()
        return None if row is None else _message_from_row(row)

    def get_by_client_request(self, sender_id: str, client_request_id: str) -> Message | None:
        row = self._connection.execute(
            """SELECT messages.*, users.username AS sender_username
               FROM messages JOIN users ON users.id = messages.sender_id
               WHERE messages.sender_id = ? AND messages.client_request_id = ?""",
            (sender_id, client_request_id),
        ).fetchone()
        return None if row is None else _message_from_row(row)

    def list_page(
        self, channel_id: str, *, limit: int, before_sequence: int | None
    ) -> list[tuple[int, Message]]:
        condition = "" if before_sequence is None else "AND sequence < ?"
        parameters: tuple[object, ...]
        if before_sequence is None:
            parameters = (channel_id, limit)
        else:
            parameters = (channel_id, before_sequence, limit)
        rows = self._connection.execute(
            f"""SELECT messages.*, users.username AS sender_username
                FROM messages JOIN users ON users.id = messages.sender_id
                WHERE messages.channel_id = ? {condition}
                ORDER BY messages.sequence DESC LIMIT ?""",
            parameters,
        ).fetchall()
        return [(row["sequence"], _message_from_row(row)) for row in rows]

    def list_context(
        self,
        channel_id: str,
        *,
        limit: int,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[Message]:
        clauses = ["messages.channel_id = ?"]
        parameters: list[object] = [channel_id]
        if from_time is not None:
            clauses.append("messages.created_at >= ?")
            parameters.append(_to_text(from_time))
        if to_time is not None:
            clauses.append("messages.created_at <= ?")
            parameters.append(_to_text(to_time))
        parameters.append(limit)
        rows = self._connection.execute(
            f"""SELECT messages.*, users.username AS sender_username
                FROM messages JOIN users ON users.id = messages.sender_id
                WHERE {' AND '.join(clauses)}
                ORDER BY messages.sequence DESC LIMIT ?""",
            tuple(parameters),
        ).fetchall()
        return [_message_from_row(row) for row in reversed(rows)]


class SQLiteFileRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, metadata: FileMetadata, client_request_id: str) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO files(
                id, channel_id, message_id, uploader_id, original_name,
                storage_reference, content_type, size_bytes, checksum_sha256,
                created_at, client_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.id,
                metadata.channel_id,
                metadata.message_id,
                metadata.uploader_id,
                metadata.original_name,
                metadata.storage_reference,
                metadata.content_type,
                metadata.size_bytes,
                metadata.checksum_sha256,
                _to_text(metadata.created_at),
                client_request_id,
            ),
        )
        return cursor.rowcount > 0

    def get(self, file_id: str) -> FileMetadata | None:
        row = self._connection.execute(
            """SELECT files.*, users.username AS uploader_username
               FROM files JOIN users ON users.id = files.uploader_id
               WHERE files.id = ?""",
            (file_id,),
        ).fetchone()
        return None if row is None else _file_from_row(row)

    def get_by_client_request(
        self, uploader_id: str, client_request_id: str
    ) -> FileMetadata | None:
        row = self._connection.execute(
            """SELECT files.*, users.username AS uploader_username
               FROM files JOIN users ON users.id = files.uploader_id
               WHERE files.uploader_id = ? AND files.client_request_id = ?""",
            (uploader_id, client_request_id),
        ).fetchone()
        return None if row is None else _file_from_row(row)

    def list_page(
        self, channel_id: str, *, limit: int, before_sequence: int | None
    ) -> list[tuple[int, FileMetadata]]:
        condition = "" if before_sequence is None else "AND files.rowid < ?"
        parameters: tuple[object, ...]
        if before_sequence is None:
            parameters = (channel_id, limit)
        else:
            parameters = (channel_id, before_sequence, limit)
        rows = self._connection.execute(
            f"""SELECT files.*, files.rowid AS file_sequence,
                       users.username AS uploader_username
                FROM files JOIN users ON users.id = files.uploader_id
                WHERE files.channel_id = ? {condition}
                ORDER BY files.rowid DESC LIMIT ?""",
            parameters,
        ).fetchall()
        return [(row["file_sequence"], _file_from_row(row)) for row in rows]


class SQLiteUnitOfWork:
    def __init__(self, database: Database, *, immediate: bool = False) -> None:
        self._database = database
        self._immediate = immediate
        self.connection: sqlite3.Connection | None = None
        self.users: SQLiteUserRepository
        self.sessions: SQLiteSessionRepository
        self.channels: SQLiteChannelRepository
        self.messages: SQLiteMessageRepository
        self.files: SQLiteFileRepository
        self._committed = False

    def __enter__(self) -> SQLiteUnitOfWork:
        self.connection = self._database.connect()
        # Command handlers may reserve SQLite's single writer slot before they
        # read state that they subsequently update. Read-only/nested operations
        # retain ordinary deferred transactions.
        self.connection.execute("BEGIN IMMEDIATE" if self._immediate else "BEGIN")
        self.users = SQLiteUserRepository(self.connection)
        self.sessions = SQLiteSessionRepository(self.connection)
        self.channels = SQLiteChannelRepository(self.connection)
        self.messages = SQLiteMessageRepository(self.connection)
        self.files = SQLiteFileRepository(self.connection)
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

    def __call__(self, *, immediate: bool = False) -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(self._database, immediate=immediate)


def is_unique_violation(error: sqlite3.IntegrityError) -> bool:
    return "UNIQUE constraint failed" in str(error)
