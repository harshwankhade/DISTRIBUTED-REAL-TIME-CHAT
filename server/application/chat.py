"""Channel messaging application logic."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from common.errors import ApplicationError, ErrorCode
from common.metadata import utc_now
from domain.models import Message
from server.application.auth import AuthApplication
from server.application.commands import SendMessageCommand
from server.events import EventBroker
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class HistoryPage:
    messages: tuple[Message, ...]
    next_page_token: str


class ChatApplication:
    def __init__(self, factory: SQLiteUnitOfWorkFactory, auth: AuthApplication,
                 events: EventBroker, *, max_message_length: int) -> None:
        self._factory = factory
        self._auth = auth
        self._events = events
        self._max_length = max_message_length

    def _require_channel_member(self, unit_of_work, channel_id: str, user_id: str,
                                request_id: str, *, allow_archived: bool) -> None:
        channel = unit_of_work.channels.get(channel_id)
        if channel is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
        if channel.is_archived and not allow_archived:
            raise ApplicationError(ErrorCode.CONFLICT, "channel is archived", request_id)
        if not unit_of_work.channels.is_member(channel_id, user_id):
            raise ApplicationError(
                ErrorCode.PERMISSION_DENIED, "channel membership required", request_id
            )

    def send_message(self, token: str | None, channel_id: str, body: str,
                     client_request_id: str, *, request_id: str) -> Message:
        user = self._auth.authenticate(token, request_id=request_id)
        normalized_body = body.strip()
        if not normalized_body:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "message body is required", request_id)
        if len(normalized_body) > self._max_length:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "message body is too long", request_id)
        command = SendMessageCommand(
            str(uuid4()), channel_id, user.id, normalized_body, utc_now(), client_request_id
        )
        candidate = Message(
            command.message_id, command.channel_id, command.sender_id, command.body,
            command.created_at, command.client_request_id,
        )
        created = False
        with self._factory(immediate=True) as unit_of_work:
            self._require_channel_member(
                unit_of_work, channel_id, user.id, request_id, allow_archived=False
            )
            created = unit_of_work.messages.add(candidate)
            result = candidate if created else unit_of_work.messages.get_by_client_request(
                user.id, client_request_id
            )
            if result is None:
                raise ApplicationError(ErrorCode.INTERNAL, "message idempotency lookup failed", request_id)
            if result.channel_id != channel_id or result.body != normalized_body:
                raise ApplicationError(
                    ErrorCode.CONFLICT,
                    "client_request_id was already used for different message content",
                    request_id,
                )
            unit_of_work.commit()
        if created:
            self._events.publish("message", result, result.created_at)
        return result

    def get_history(self, token: str | None, channel_id: str, page_size: int,
                    page_token: str, *, request_id: str) -> HistoryPage:
        user = self._auth.authenticate(token, request_id=request_id)
        limit = 50 if page_size == 0 else page_size
        if limit < 1 or limit > 100:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "page_size must be 1-100", request_id)
        before: int | None = None
        if page_token:
            try:
                before = int(page_token)
            except ValueError as exc:
                raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "invalid page_token", request_id) from exc
            if before <= 0:
                raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "invalid page_token", request_id)
        with self._factory() as unit_of_work:
            self._require_channel_member(
                unit_of_work, channel_id, user.id, request_id, allow_archived=True
            )
            rows = unit_of_work.messages.list_page(
                channel_id, limit=limit + 1, before_sequence=before
            )
        has_more = len(rows) > limit
        selected = rows[:limit]
        next_token = str(selected[-1][0]) if has_more and selected else ""
        return HistoryPage(tuple(message for _, message in selected), next_token)

    def authorize_subscription(self, token: str | None, channel_ids: list[str],
                               *, request_id: str) -> set[str]:
        user = self._auth.authenticate(token, request_id=request_id)
        unique_ids = set(channel_ids)
        with self._factory() as unit_of_work:
            for channel_id in unique_ids:
                self._require_channel_member(
                    unit_of_work, channel_id, user.id, request_id, allow_archived=True
                )
        return unique_ids
