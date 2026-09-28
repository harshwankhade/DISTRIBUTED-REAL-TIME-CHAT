"""Typed gRPC client used only by the chat application to call Node 1."""

from __future__ import annotations

from datetime import datetime

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from common.grpc_metadata import REQUEST_ID_HEADER
from domain.models import Message
from proto.chat.v1 import common_pb2, llm_pb2, llm_pb2_grpc


def _timestamp(value: datetime) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _items(messages: tuple[Message, ...]) -> list[llm_pb2.ConversationItem]:
    return [
        llm_pb2.ConversationItem(
            message_id=message.id,
            sender_id=message.sender_id,
            body=message.body,
            created_at=_timestamp(message.created_at),
        )
        for message in messages
    ]


class LLMClient:
    def __init__(self, target: str, *, timeout_seconds: float) -> None:
        self._channel = grpc.insecure_channel(target)
        self._stub = llm_pb2_grpc.LLMServiceStub(self._channel)
        self._timeout = timeout_seconds

    def close(self) -> None:
        self._channel.close()

    def smart_reply(self, requester_id: str, channel_id: str,
                    messages: tuple[Message, ...], *, request_id: str) -> str:
        response = self._stub.GetSmartReply(
            llm_pb2.SmartReplyRequest(
                context=common_pb2.RequestContext(request_id=request_id),
                requester_id=requester_id,
                channel_id=channel_id,
                authorized_context=_items(messages),
            ),
            timeout=self._timeout,
            metadata=((REQUEST_ID_HEADER, request_id),),
        )
        return response.answer

    def summary(self, requester_id: str, channel_id: str,
                messages: tuple[Message, ...], from_time: datetime,
                to_time: datetime, *, request_id: str) -> str:
        response = self._stub.SummarizeConversation(
            llm_pb2.SummaryRequest(
                context=common_pb2.RequestContext(request_id=request_id),
                requester_id=requester_id,
                channel_id=channel_id,
                from_time=_timestamp(from_time),
                to_time=_timestamp(to_time),
                authorized_context=_items(messages),
            ),
            timeout=self._timeout,
            metadata=((REQUEST_ID_HEADER, request_id),),
        )
        return response.answer

    def suggestion(self, requester_id: str, channel_id: str,
                   messages: tuple[Message, ...], *, request_id: str) -> str:
        response = self._stub.GetSuggestion(
            llm_pb2.SuggestionRequest(
                context=common_pb2.RequestContext(request_id=request_id),
                requester_id=requester_id,
                channel_id=channel_id,
                authorized_context=_items(messages),
            ),
            timeout=self._timeout,
            metadata=((REQUEST_ID_HEADER, request_id),),
        )
        return response.answer
