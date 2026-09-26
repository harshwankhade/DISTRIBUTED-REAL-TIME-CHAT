"""Transient heartbeat-based presence tracking."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock

from common.metadata import utc_now
from domain.models import Presence, PresenceStatus
from server.application.auth import AuthApplication
from server.events import EventBroker
from server.security.tokens import hash_session_token


class PresenceApplication:
    def __init__(self, auth: AuthApplication, events: EventBroker, *, timeout_seconds: float,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._auth = auth
        self._events = events
        self._timeout = timedelta(seconds=timeout_seconds)
        self._clock = clock
        self._heartbeats: dict[tuple[str, str], datetime] = {}
        self._last_seen: dict[str, datetime] = {}
        self._online: set[str] = set()
        self._lock = Lock()

    def _expire_locked(self, now: datetime) -> list[Presence]:
        expired = [key for key, seen in self._heartbeats.items() if now - seen >= self._timeout]
        for key in expired:
            del self._heartbeats[key]
        changed: list[Presence] = []
        for user_id in tuple(self._online):
            if not any(key[0] == user_id for key in self._heartbeats):
                self._online.remove(user_id)
                changed.append(Presence(user_id, PresenceStatus.OFFLINE, self._last_seen[user_id]))
        return changed

    def expire(self) -> None:
        with self._lock:
            changed = self._expire_locked(self._clock())
        for presence in changed:
            self._events.publish("presence", presence, presence.last_seen_at)

    def heartbeat(self, token: str | None, *, request_id: str) -> Presence:
        user = self._auth.authenticate(token, request_id=request_id)
        assert token is not None
        now = self._clock()
        with self._lock:
            expired = self._expire_locked(now)
            became_online = user.id not in self._online
            self._heartbeats[(user.id, hash_session_token(token))] = now
            self._last_seen[user.id] = now
            self._online.add(user.id)
            result = Presence(user.id, PresenceStatus.ONLINE, now)
        for presence in expired:
            self._events.publish("presence", presence, presence.last_seen_at)
        if became_online:
            self._events.publish("presence", result, now)
        return result

    def get(self, token: str | None, user_id: str, *, request_id: str) -> Presence:
        self._auth.authenticate(token, request_id=request_id)
        self.expire()
        with self._lock:
            last_seen = self._last_seen.get(user_id)
            online = user_id in self._online
        if last_seen is None:
            last_seen = self._clock()
        return Presence(
            user_id,
            PresenceStatus.ONLINE if online else PresenceStatus.OFFLINE,
            last_seen,
        )

    def authenticate_subscription(self, token: str | None, *, request_id: str) -> None:
        self._auth.authenticate(token, request_id=request_id)
