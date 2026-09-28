from __future__ import annotations

import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from common.config import load_settings
from common.grpc_metadata import MetadataClientInterceptor
from llm_server.adapters import DeterministicMockAdapter, LLMTask
from llm_server.grpc_server import create_llm_server
from proto.chat.v1 import (
    auth_pb2,
    auth_pb2_grpc,
    channel_pb2,
    channel_pb2_grpc,
    chat_pb2,
    chat_pb2_grpc,
    common_pb2,
    llm_pb2,
    llm_pb2_grpc,
)
from server.database import Database
from server.grpc_server import create_chat_server
from server.seed import seed_users


PASSWORD = "sample-password-123"
ADMIN_PASSWORD = "admin-password-123"


class SlowAdapter:
    def generate(self, task, context):
        time.sleep(0.4)
        return "too late"


def _timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


class Phase4LLMIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.database = Database(root / "chat.db")
        seed_users(
            self.database,
            admin_username="admin",
            admin_password=ADMIN_PASSWORD,
            sample_usernames=["alice", "bob", "outsider"],
            sample_password=PASSWORD,
        )
        self.adapter = DeterministicMockAdapter()
        llm_settings = load_settings({"LLM_ADAPTER": "mock", "RPC_TIMEOUT_SECONDS": "2"})
        self.llm_server, self.llm_target = create_llm_server(
            llm_settings, bind_address="127.0.0.1:0", adapter=self.adapter
        )
        self.llm_server.start()
        llm_host, llm_port = self.llm_target.rsplit(":", 1)
        self.settings = load_settings(
            {
                "CHAT_DATABASE_PATH": str(self.database.path),
                "FILE_STORAGE_PATH": str(root / "uploads"),
                "LLM_HOST": llm_host,
                "LLM_PORT": llm_port,
                "LLM_MAX_CONTEXT_MESSAGES": "2",
                "LLM_MAX_CONTEXT_CHARS": "40",
                "LLM_REQUEST_TIMEOUT_SECONDS": "0.1",
                "RPC_TIMEOUT_SECONDS": "2",
            }
        )
        self.chat_server, self.chat_target = create_chat_server(
            self.settings, bind_address="127.0.0.1:0"
        )
        self.chat_server.start()
        self.tokens = {
            name: self._login(name, PASSWORD)
            for name in ("alice", "bob", "outsider")
        }
        self.channel_a = self._create_channel("private-a")
        self.channel_b = self._create_channel("private-b")
        for name in ("alice", "bob"):
            self._join(name, self.channel_a)
        self._join("bob", self.channel_b)

    def tearDown(self) -> None:
        self.chat_server.stop(0).wait()
        self.llm_server.stop(0).wait()
        self.directory.cleanup()

    def _channel(self, request_id: str, user: str | None = None) -> grpc.Channel:
        token = None if user is None else self.tokens[user]
        return grpc.intercept_channel(
            grpc.insecure_channel(self.chat_target),
            MetadataClientInterceptor(request_id=request_id, token=token),
        )

    def _login(self, username: str, password: str) -> str:
        request_id = f"login-{username}"
        channel = self._channel(request_id)
        try:
            return auth_pb2_grpc.AuthServiceStub(channel).Login(
                auth_pb2.LoginRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    username=username,
                    password=password,
                ), timeout=2,
            ).token
        finally:
            channel.close()

    def _create_channel(self, name: str) -> str:
        request_id = f"create-{name}"
        channel = self._channel(request_id, "alice")
        try:
            return channel_pb2_grpc.ChannelServiceStub(channel).CreateChannel(
                channel_pb2.CreateChannelRequest(
                    context=common_pb2.RequestContext(request_id=request_id), name=name
                ), timeout=2,
            ).channel.channel_id
        finally:
            channel.close()

    def _join(self, username: str, channel_id: str) -> None:
        if username == "alice":
            return
        request_id = f"join-{username}-{channel_id}"
        channel = self._channel(request_id, username)
        try:
            channel_pb2_grpc.ChannelServiceStub(channel).JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    channel_id=channel_id,
                ), timeout=2,
            )
        finally:
            channel.close()
        owner_channel = self._channel(f"approve-{username}-{channel_id}", "alice")
        try:
            stub = channel_pb2_grpc.ChannelServiceStub(owner_channel)
            pending = stub.ListJoinRequests(
                channel_pb2.ListJoinRequestsRequest(
                    context=common_pb2.RequestContext(request_id=f"pending-{username}"),
                    channel_id=channel_id,
                ), timeout=2,
            ).requests
            match = next(item for item in pending if item.user.username == username)
            stub.DecideJoinRequest(
                channel_pb2.DecideJoinRequestRequest(
                    context=common_pb2.RequestContext(request_id=f"approve-{username}"),
                    join_request_id=match.request_id,
                    approve=True,
                ), timeout=2,
            )
        finally:
            owner_channel.close()

    def _send(self, username: str, channel_id: str, body: str):
        request_id = f"send-{time.time_ns()}"
        channel = self._channel(request_id, username)
        try:
            return chat_pb2_grpc.ChatServiceStub(channel).SendMessage(
                chat_pb2.SendMessageRequest(
                    context=common_pb2.RequestContext(
                        request_id=request_id, client_request_id=request_id
                    ),
                    channel_id=channel_id,
                    body=body,
                ), timeout=2,
            ).message
        finally:
            channel.close()

    def _assistant(self, request_id: str, username: str):
        channel = self._channel(request_id, username)
        return channel, llm_pb2_grpc.LLMServiceStub(channel)

    def test_gateway_ignores_forged_context_and_filters_by_membership(self) -> None:
        self._send("bob", self.channel_b, "SECRET FROM CHANNEL B")
        self._send("bob", self.channel_a, "public first")
        self._send("alice", self.channel_a, "authorized latest")
        fake = llm_pb2.ConversationItem(
            message_id="forged",
            sender_id="outsider",
            body="FORGED CLIENT CONTEXT",
            created_at=_timestamp(datetime.now(UTC)),
        )
        channel, stub = self._assistant("assistant-private", "alice")
        try:
            response = stub.GetSmartReply(
                llm_pb2.SmartReplyRequest(
                    context=common_pb2.RequestContext(request_id="assistant-private"),
                    requester_id="outsider",
                    channel_id=self.channel_a,
                    authorized_context=[fake],
                ), timeout=2,
            )
        finally:
            channel.close()

        self.assertEqual(response.answer, "Mock reply to: authorized latest")
        task, turns = self.adapter.calls[-1]
        self.assertEqual(task, LLMTask.SMART_REPLY)
        bodies = [turn.body for turn in turns]
        self.assertEqual(bodies, ["public first", "authorized latest"])
        self.assertNotIn("SECRET FROM CHANNEL B", bodies)
        self.assertNotIn("FORGED CLIENT CONTEXT", bodies)

        before = len(self.adapter.calls)
        channel, stub = self._assistant("assistant-outsider", "outsider")
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                stub.GetSuggestion(
                    llm_pb2.SuggestionRequest(
                        context=common_pb2.RequestContext(request_id="assistant-outsider"),
                        channel_id=self.channel_a,
                    ), timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        self.assertEqual(len(self.adapter.calls), before)

    def test_summary_time_range_and_context_bounds(self) -> None:
        first = self._send("alice", self.channel_a, "old-message")
        lower = first.created_at.ToDatetime(tzinfo=UTC) + timedelta(microseconds=1)
        second = self._send("bob", self.channel_a, "second-message")
        self._send("alice", self.channel_a, "newest-message-is-long")
        upper = datetime.now(UTC) + timedelta(seconds=1)

        channel, stub = self._assistant("summary-range", "alice")
        try:
            response = stub.SummarizeConversation(
                llm_pb2.SummaryRequest(
                    context=common_pb2.RequestContext(request_id="summary-range"),
                    channel_id=self.channel_a,
                    from_time=_timestamp(lower),
                    to_time=_timestamp(upper),
                ), timeout=2,
            )
        finally:
            channel.close()
        self.assertEqual(response.answer, "Mock summary of 2 authorized message(s).")
        task, turns = self.adapter.calls[-1]
        self.assertEqual(task, LLMTask.SUMMARY)
        self.assertEqual(len(turns), 2)
        self.assertNotIn("old-message", [turn.body for turn in turns])
        self.assertLessEqual(sum(len(turn.body) for turn in turns), 40)
        self.assertIn(second.message_id, [turn.message_id for turn in turns])

    def test_llm_offline_returns_fallback_and_chat_remains_available(self) -> None:
        self._send("alice", self.channel_a, "before outage")
        self.llm_server.stop(0).wait()
        channel, stub = self._assistant("offline-ai", "alice")
        try:
            response = stub.GetSuggestion(
                llm_pb2.SuggestionRequest(
                    context=common_pb2.RequestContext(request_id="offline-ai"),
                    channel_id=self.channel_a,
                ), timeout=2,
            )
        finally:
            channel.close()
        self.assertIn("graceful fallback", response.status.message)
        self.assertIn("unavailable", response.answer.lower())

        sent = self._send("bob", self.channel_a, "chat still works")
        self.assertEqual(sent.body, "chat still works")

    def test_llm_deadline_returns_graceful_fallback(self) -> None:
        self.llm_server.stop(0).wait()
        slow_settings = load_settings({"LLM_ADAPTER": "mock"})
        self.llm_server, _ = create_llm_server(
            slow_settings, bind_address=self.llm_target, adapter=SlowAdapter()
        )
        self.llm_server.start()
        started = time.monotonic()
        channel, stub = self._assistant("slow-ai", "alice")
        try:
            response = stub.GetSmartReply(
                llm_pb2.SmartReplyRequest(
                    context=common_pb2.RequestContext(request_id="slow-ai"),
                    channel_id=self.channel_a,
                ), timeout=2,
            )
        finally:
            channel.close()
        self.assertLess(time.monotonic() - started, 0.35)
        self.assertIn("graceful fallback", response.status.message)


if __name__ == "__main__":
    unittest.main()
