"""Authenticated context construction and LLM orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import grpc

from common.errors import ApplicationError, ErrorCode
from domain.models import Message, User
from server.application.auth import AuthApplication
from server.llm_client import LLMClient
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class AssistantResult:
    answer: str
    model_available: bool


class AuthorizedContextBuilder:
    def __init__(self, factory: SQLiteUnitOfWorkFactory, auth: AuthApplication, *,
                 max_messages: int, max_chars: int) -> None:
        self._factory = factory
        self._auth = auth
        self._max_messages = max_messages
        self._max_chars = max_chars

    def build(self, token: str | None, channel_id: str, *, request_id: str,
              from_time: datetime | None = None,
              to_time: datetime | None = None) -> tuple[User, tuple[Message, ...]]:
        user = self._auth.authenticate(token, request_id=request_id)
        with self._factory() as unit_of_work:
            channel = unit_of_work.channels.get(channel_id)
            if channel is None:
                raise ApplicationError(ErrorCode.NOT_FOUND, "channel not found", request_id)
            if not unit_of_work.channels.is_member(channel_id, user.id):
                raise ApplicationError(ErrorCode.PERMISSION_DENIED, "channel membership required", request_id)
            messages = unit_of_work.messages.list_context(
                channel_id,
                limit=self._max_messages,
                from_time=from_time,
                to_time=to_time,
            )

        selected: list[Message] = []
        remaining = self._max_chars
        for message in reversed(messages):
            if remaining <= 0:
                break
            body = message.body[:remaining]
            selected.append(
                message if body == message.body else Message(
                    message.id, message.channel_id, message.sender_id, body,
                    message.created_at, message.client_request_id,
                )
            )
            remaining -= len(body)
        selected.reverse()
        return user, tuple(selected)


class AssistantApplication:
    _FALLBACKS = {
        "smart": "AI is currently unavailable. You can still reply manually.",
        "summary": "AI summary is currently unavailable; chat history remains available.",
        "suggestion": "AI suggestions are currently unavailable; normal chat is unaffected.",
    }

    def __init__(self, context_builder: AuthorizedContextBuilder, client: LLMClient) -> None:
        self._context_builder = context_builder
        self._client = client

    @staticmethod
    def _validate_range(from_time: datetime, to_time: datetime, request_id: str) -> None:
        if from_time.tzinfo is None or to_time.tzinfo is None:
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "summary times must include UTC timezone", request_id)
        if from_time.astimezone(UTC) >= to_time.astimezone(UTC):
            raise ApplicationError(ErrorCode.INVALID_ARGUMENT, "from_time must be before to_time", request_id)

    def _call(self, operation: str, callback) -> AssistantResult:
        try:
            return AssistantResult(callback(), True)
        except grpc.RpcError:
            return AssistantResult(self._FALLBACKS[operation], False)

    def smart_reply(self, token: str | None, channel_id: str, *, request_id: str) -> AssistantResult:
        user, messages = self._context_builder.build(token, channel_id, request_id=request_id)
        return self._call(
            "smart",
            lambda: self._client.smart_reply(user.id, channel_id, messages, request_id=request_id),
        )

    def summarize(self, token: str | None, channel_id: str, from_time: datetime,
                  to_time: datetime, *, request_id: str) -> AssistantResult:
        self._validate_range(from_time, to_time, request_id)
        user, messages = self._context_builder.build(
            token, channel_id, request_id=request_id,
            from_time=from_time.astimezone(UTC), to_time=to_time.astimezone(UTC),
        )
        return self._call(
            "summary",
            lambda: self._client.summary(
                user.id, channel_id, messages, from_time, to_time, request_id=request_id
            ),
        )

    def suggestion(self, token: str | None, channel_id: str, *, request_id: str) -> AssistantResult:
        user, messages = self._context_builder.build(token, channel_id, request_id=request_id)
        return self._call(
            "suggestion",
            lambda: self._client.suggestion(user.id, channel_id, messages, request_id=request_id),
        )
