"""Authentication and session lifecycle application logic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from common.errors import ApplicationError, ErrorCode
from common.metadata import utc_now
from domain.models import Session, User, UserRole, UserStatus
from server.repositories.sqlite import SQLiteUnitOfWorkFactory
from server.security.passwords import hash_password, verify_password
from server.security.tokens import generate_session_token, hash_session_token


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    expires_at: datetime
    user: User


class AuthApplication:
    def __init__(
        self,
        unit_of_work_factory: SQLiteUnitOfWorkFactory,
        *,
        session_ttl_seconds: int,
        clock: Callable[[], datetime] = utc_now,
        token_generator: Callable[[], str] = generate_session_token,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._session_ttl = timedelta(seconds=session_ttl_seconds)
        self._clock = clock
        self._token_generator = token_generator
        self._dummy_password_hash = hash_password("invalid-password-placeholder")

    def login(self, username: str, password: str, *, request_id: str) -> LoginResult:
        normalized_username = username.strip()
        if not normalized_username or not password:
            raise ApplicationError(
                ErrorCode.INVALID_ARGUMENT,
                "username and password are required",
                request_id,
            )

        with self._unit_of_work_factory() as unit_of_work:
            stored = unit_of_work.users.get_by_username(normalized_username)
            encoded_hash = (
                self._dummy_password_hash if stored is None else stored.password_hash
            )
            password_valid = verify_password(password, encoded_hash)
            if stored is None or not password_valid:
                raise ApplicationError(
                    ErrorCode.UNAUTHENTICATED,
                    "invalid username or password",
                    request_id,
                )
            if stored.user.status is UserStatus.DISABLED:
                raise ApplicationError(
                    ErrorCode.PERMISSION_DENIED,
                    "account is disabled",
                    request_id,
                )

            now = self._clock()
            expires_at = now + self._session_ttl
            raw_token = self._token_generator()
            session = Session(
                id=str(uuid4()),
                user_id=stored.user.id,
                token_hash=hash_session_token(raw_token),
                created_at=now,
                expires_at=expires_at,
            )
            unit_of_work.sessions.add(session)
            unit_of_work.commit()
            return LoginResult(raw_token, expires_at, stored.user)

    def authenticate(self, token: str | None, *, request_id: str) -> User:
        if token is None or not token.strip():
            raise ApplicationError(
                ErrorCode.UNAUTHENTICATED, "valid bearer token required", request_id
            )
        token_hash = hash_session_token(token)
        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.get_by_token_hash(token_hash)
            if session is None or session.revoked_at is not None:
                raise ApplicationError(
                    ErrorCode.UNAUTHENTICATED, "session is invalid", request_id
                )
            if session.expires_at <= now:
                unit_of_work.sessions.revoke(token_hash, now)
                unit_of_work.commit()
                raise ApplicationError(
                    ErrorCode.UNAUTHENTICATED, "session has expired", request_id
                )
            stored = unit_of_work.users.get(session.user_id)
            if stored is None:
                raise ApplicationError(
                    ErrorCode.UNAUTHENTICATED, "session user no longer exists", request_id
                )
            if stored.user.status is UserStatus.DISABLED:
                raise ApplicationError(
                    ErrorCode.PERMISSION_DENIED, "account is disabled", request_id
                )
            return stored.user

    def require_admin(self, token: str | None, *, request_id: str) -> User:
        user = self.authenticate(token, request_id=request_id)
        if user.role is not UserRole.ADMIN:
            raise ApplicationError(
                ErrorCode.PERMISSION_DENIED, "administrator role required", request_id
            )
        return user

    def logout(self, token: str | None, *, request_id: str) -> None:
        self.authenticate(token, request_id=request_id)
        assert token is not None
        with self._unit_of_work_factory() as unit_of_work:
            revoked = unit_of_work.sessions.revoke(
                hash_session_token(token), self._clock()
            )
            if not revoked:
                raise ApplicationError(
                    ErrorCode.UNAUTHENTICATED, "session is invalid", request_id
                )
            unit_of_work.commit()

