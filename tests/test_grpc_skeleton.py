from __future__ import annotations

import unittest

import grpc

from client.grpc_client import run_smoke_test
from common.config import load_settings
from common.grpc_metadata import MetadataClientInterceptor
from llm_server.grpc_server import create_llm_server
from proto.chat.v1 import (
    auth_pb2,
    auth_pb2_grpc,
    chat_pb2,
    chat_pb2_grpc,
    common_pb2,
    health_pb2,
    health_pb2_grpc,
    llm_pb2,
    llm_pb2_grpc,
)
from server.grpc_server import create_chat_server


def _channel(target: str, request_id: str, token: str | None = None) -> grpc.Channel:
    return grpc.intercept_channel(
        grpc.insecure_channel(target),
        MetadataClientInterceptor(request_id=request_id, token=token),
    )


class ChatGrpcSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings(
            {"STREAM_KEEPALIVE_SECONDS": "0.05", "RPC_TIMEOUT_SECONDS": "2"}
        )
        cls.server, cls.target = create_chat_server(
            cls.settings, bind_address="127.0.0.1:0"
        )
        cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop(0).wait()

    def test_health_echoes_request_id_and_extracts_token(self) -> None:
        request_id = "health-request-1"
        channel = _channel(self.target, request_id, token="test-token")
        try:
            response = health_pb2_grpc.HealthServiceStub(channel).Check(
                health_pb2.HealthCheckRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    service="chat-server",
                ),
                timeout=2,
            )
        finally:
            channel.close()
        self.assertTrue(response.serving)
        self.assertEqual(response.status.request_id, request_id)
        self.assertTrue(response.auth_metadata_present)

    def test_login_skeleton_returns_unimplemented(self) -> None:
        request_id = "login-request-1"
        channel = _channel(self.target, request_id)
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                auth_pb2_grpc.AuthServiceStub(channel).Login(
                    auth_pb2.LoginRequest(
                        context=common_pb2.RequestContext(request_id=request_id),
                        username="alice",
                        password="not-a-real-password",
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.UNIMPLEMENTED)

    def test_invalid_login_returns_invalid_argument(self) -> None:
        request_id = "invalid-login-1"
        channel = _channel(self.target, request_id)
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                auth_pb2_grpc.AuthServiceStub(channel).Login(
                    auth_pb2.LoginRequest(
                        context=common_pb2.RequestContext(request_id=request_id),
                        username="",
                        password="value",
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.INVALID_ARGUMENT)
        self.assertIn("username", captured.exception.details())

    def test_subscription_emits_keepalive_and_accepts_cancellation(self) -> None:
        request_id = "stream-request-1"
        channel = _channel(self.target, request_id)
        try:
            call = chat_pb2_grpc.ChatServiceStub(channel).SubscribeEvents(
                chat_pb2.SubscribeEventsRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    channel_ids=["channel-1"],
                ),
                timeout=2,
            )
            event = next(call)
            self.assertEqual(event.type, chat_pb2.CHAT_EVENT_TYPE_KEEPALIVE)
            self.assertEqual(event.request_id, request_id)
            self.assertTrue(call.cancel())
            self.assertEqual(call.code(), grpc.StatusCode.CANCELLED)
        finally:
            channel.close()

    def test_smoke_client_covers_acceptance_path(self) -> None:
        result = run_smoke_test(target=self.target, timeout_seconds=2)
        self.assertTrue(result.health_serving)
        self.assertEqual(result.login_status, "UNIMPLEMENTED")
        self.assertEqual(result.stream_event_type, "CHAT_EVENT_TYPE_KEEPALIVE")
        self.assertTrue(result.stream_cancelled)


class LlmGrpcSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings({"RPC_TIMEOUT_SECONDS": "2"})
        cls.server, cls.target = create_llm_server(
            cls.settings, bind_address="127.0.0.1:0"
        )
        cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop(0).wait()

    def test_llm_service_is_separate_and_unimplemented(self) -> None:
        request_id = "llm-request-1"
        channel = _channel(self.target, request_id)
        try:
            health = health_pb2_grpc.HealthServiceStub(channel).Check(
                health_pb2.HealthCheckRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    service="llm-server",
                ),
                timeout=2,
            )
            self.assertEqual(health.service, "llm-server")
            with self.assertRaises(grpc.RpcError) as captured:
                llm_pb2_grpc.LLMServiceStub(channel).GetSmartReply(
                    llm_pb2.SmartReplyRequest(
                        context=common_pb2.RequestContext(request_id=request_id),
                        requester_id="user-1",
                        channel_id="channel-1",
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.UNIMPLEMENTED)


if __name__ == "__main__":
    unittest.main()

