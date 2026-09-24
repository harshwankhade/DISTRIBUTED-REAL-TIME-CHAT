"""Small typed client used to verify the Phase 1 gRPC skeleton."""

from __future__ import annotations

from dataclasses import dataclass

import grpc

from common.grpc_metadata import MetadataClientInterceptor
from common.metadata import new_request_id
from proto.chat.v1 import (
    auth_pb2,
    auth_pb2_grpc,
    chat_pb2,
    chat_pb2_grpc,
    common_pb2,
    health_pb2,
    health_pb2_grpc,
)


@dataclass(frozen=True, slots=True)
class SmokeResult:
    health_serving: bool
    health_request_id: str
    login_status: str
    stream_event_type: str
    stream_cancelled: bool


def _intercepted_channel(
    base_channel: grpc.Channel, *, request_id: str, token: str | None = None
) -> grpc.Channel:
    return grpc.intercept_channel(
        base_channel,
        MetadataClientInterceptor(request_id=request_id, token=token),
    )


def run_smoke_test(
    *, target: str, timeout_seconds: float, username: str, password: str
) -> SmokeResult:
    """Exercise health, login, authenticated streaming, and cancellation."""

    base_channel = grpc.insecure_channel(target)
    try:
        health_request_id = new_request_id()
        health_stub = health_pb2_grpc.HealthServiceStub(
            _intercepted_channel(base_channel, request_id=health_request_id)
        )
        health = health_stub.Check(
            health_pb2.HealthCheckRequest(
                context=common_pb2.RequestContext(request_id=health_request_id),
                service="chat-server",
            ),
            timeout=timeout_seconds,
        )

        login_request_id = new_request_id()
        auth_stub = auth_pb2_grpc.AuthServiceStub(
            _intercepted_channel(base_channel, request_id=login_request_id)
        )
        login = auth_stub.Login(
            auth_pb2.LoginRequest(
                context=common_pb2.RequestContext(request_id=login_request_id),
                username=username,
                password=password,
            ),
            timeout=timeout_seconds,
        )
        login_status = "OK"

        stream_request_id = new_request_id()
        chat_stub = chat_pb2_grpc.ChatServiceStub(
            _intercepted_channel(
                base_channel, request_id=stream_request_id, token=login.token
            )
        )
        stream = chat_stub.SubscribeEvents(
            chat_pb2.SubscribeEventsRequest(
                context=common_pb2.RequestContext(request_id=stream_request_id),
                channel_ids=["phase1-smoke-channel"],
            ),
            timeout=timeout_seconds,
        )
        event = next(stream)
        cancelled = stream.cancel()

        return SmokeResult(
            health_serving=health.serving,
            health_request_id=health.status.request_id,
            login_status=login_status,
            stream_event_type=chat_pb2.ChatEventType.Name(event.type),
            stream_cancelled=cancelled,
        )
    finally:
        base_channel.close()
