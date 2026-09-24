from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import grpc

from common.config import load_settings
from common.grpc_metadata import MetadataClientInterceptor
from proto.chat.v1 import (
    admin_pb2,
    admin_pb2_grpc,
    auth_pb2,
    auth_pb2_grpc,
    channel_pb2,
    channel_pb2_grpc,
    chat_pb2,
    chat_pb2_grpc,
    common_pb2,
)
from server.database import Database
from server.grpc_server import create_chat_server
from server.repositories.sqlite import SQLiteUnitOfWorkFactory
from server.seed import seed_users


ADMIN_PASSWORD = "admin-password-123"
USER_PASSWORD = "sample-password-123"


class Phase2AccessIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "chat.db"
        self.database = Database(self.database_path)
        seed_users(
            self.database,
            admin_username="admin",
            admin_password=ADMIN_PASSWORD,
            sample_usernames=["alice", "bob"],
            sample_password=USER_PASSWORD,
        )
        self.settings = load_settings(
            {
                "CHAT_DATABASE_PATH": str(self.database_path),
                "RPC_TIMEOUT_SECONDS": "2",
                "STREAM_KEEPALIVE_SECONDS": "0.05",
            }
        )
        self.server, self.target = create_chat_server(
            self.settings, bind_address="127.0.0.1:0"
        )
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop(0).wait()
        self.directory.cleanup()

    def _channel(self, request_id: str, token: str | None = None) -> grpc.Channel:
        return grpc.intercept_channel(
            grpc.insecure_channel(self.target),
            MetadataClientInterceptor(request_id=request_id, token=token),
        )

    def _login(self, username: str, password: str) -> str:
        request_id = f"login-{username}"
        channel = self._channel(request_id)
        try:
            response = auth_pb2_grpc.AuthServiceStub(channel).Login(
                auth_pb2.LoginRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    username=username,
                    password=password,
                ),
                timeout=2,
            )
            return response.token
        finally:
            channel.close()

    def _create_channel(self, admin_token: str, name: str = "general") -> str:
        request_id = f"create-{name}"
        channel = self._channel(request_id, admin_token)
        try:
            response = channel_pb2_grpc.ChannelServiceStub(channel).CreateChannel(
                channel_pb2.CreateChannelRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    name=name,
                ),
                timeout=2,
            )
            return response.channel.channel_id
        finally:
            channel.close()

    def _user_id(self, username: str) -> str:
        with SQLiteUnitOfWorkFactory(self.database)() as unit_of_work:
            return unit_of_work.users.get_by_username(username).user.id

    def test_successful_user_channel_and_logout_flow(self) -> None:
        admin_token = self._login("admin", ADMIN_PASSWORD)
        alice_token = self._login("alice", USER_PASSWORD)
        request_id = "create-charlie"
        channel = self._channel(request_id, admin_token)
        try:
            created_user = admin_pb2_grpc.AdminServiceStub(channel).CreateUser(
                admin_pb2.CreateUserRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    username="charlie",
                    password="charlie-password-123",
                    role="user",
                ),
                timeout=2,
            )
        finally:
            channel.close()
        self.assertEqual(created_user.user.username, "charlie")

        channel_id = self._create_channel(admin_token)
        manage_id = "admin-add-charlie"
        channel = self._channel(manage_id, admin_token)
        try:
            admin_pb2_grpc.AdminServiceStub(channel).ManageChannelMember(
                admin_pb2.ManageChannelMemberRequest(
                    context=common_pb2.RequestContext(request_id=manage_id),
                    channel_id=channel_id,
                    user_id=created_user.user.user_id,
                    add=True,
                ),
                timeout=2,
            )
        finally:
            channel.close()
        with SQLiteUnitOfWorkFactory(self.database)() as unit_of_work:
            self.assertTrue(
                unit_of_work.channels.is_member(
                    channel_id, created_user.user.user_id
                )
            )

        join_id = "join-alice"
        channel = self._channel(join_id, alice_token)
        try:
            channel_stub = channel_pb2_grpc.ChannelServiceStub(channel)
            channel_stub.JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id=join_id),
                    channel_id=channel_id,
                ),
                timeout=2,
            )
            listed = channel_stub.ListChannels(
                channel_pb2.ListChannelsRequest(
                    context=common_pb2.RequestContext(request_id="list-alice")
                ),
                timeout=2,
            )
            self.assertEqual([item.name for item in listed.channels], ["general"])
        finally:
            channel.close()

        logout_id = "logout-alice"
        channel = self._channel(logout_id, alice_token)
        try:
            auth_pb2_grpc.AuthServiceStub(channel).Logout(
                auth_pb2.LogoutRequest(
                    context=common_pb2.RequestContext(request_id=logout_id)
                ),
                timeout=2,
            )
            with self.assertRaises(grpc.RpcError) as captured:
                channel_pb2_grpc.ChannelServiceStub(channel).ListChannels(
                    channel_pb2.ListChannelsRequest(
                        context=common_pb2.RequestContext(request_id="after-logout")
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

    def test_normal_user_cannot_call_admin_rpc(self) -> None:
        alice_token = self._login("alice", USER_PASSWORD)
        request_id = "forbidden-admin"
        channel = self._channel(request_id, alice_token)
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                admin_pb2_grpc.AdminServiceStub(channel).CreateUser(
                    admin_pb2.CreateUserRequest(
                        context=common_pb2.RequestContext(request_id=request_id),
                        username="mallory",
                        password="mallory-password-123",
                        role="user",
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_invalid_and_disabled_sessions_are_rejected(self) -> None:
        request_id = "bad-token"
        channel = self._channel(request_id, "invalid-token")
        try:
            with self.assertRaises(grpc.RpcError) as invalid:
                channel_pb2_grpc.ChannelServiceStub(channel).ListChannels(
                    channel_pb2.ListChannelsRequest(
                        context=common_pb2.RequestContext(request_id=request_id)
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(invalid.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

        admin_token = self._login("admin", ADMIN_PASSWORD)
        alice_token = self._login("alice", USER_PASSWORD)
        disable_id = "disable-alice"
        channel = self._channel(disable_id, admin_token)
        try:
            admin_pb2_grpc.AdminServiceStub(channel).SetUserStatus(
                admin_pb2.SetUserStatusRequest(
                    context=common_pb2.RequestContext(request_id=disable_id),
                    user_id=self._user_id("alice"),
                    status="disabled",
                ),
                timeout=2,
            )
        finally:
            channel.close()

        channel = self._channel("disabled-token", alice_token)
        try:
            with self.assertRaises(grpc.RpcError) as protected:
                channel_pb2_grpc.ChannelServiceStub(channel).ListChannels(
                    channel_pb2.ListChannelsRequest(
                        context=common_pb2.RequestContext(request_id="disabled-token")
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(protected.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

        channel = self._channel("disabled-send", alice_token)
        try:
            with self.assertRaises(grpc.RpcError) as disabled_send:
                chat_pb2_grpc.ChatServiceStub(channel).SendMessage(
                    chat_pb2.SendMessageRequest(
                        context=common_pb2.RequestContext(
                            request_id="disabled-send",
                            client_request_id="disabled-send-client",
                        ),
                        channel_id="not-used-yet",
                        body="not persisted in Phase 2",
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(
            disabled_send.exception.code(), grpc.StatusCode.UNAUTHENTICATED
        )

        with self.assertRaises(grpc.RpcError) as login_denied:
            self._login("alice", USER_PASSWORD)
        self.assertEqual(login_denied.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_membership_and_archive_rules_survive_restart(self) -> None:
        admin_token = self._login("admin", ADMIN_PASSWORD)
        alice_token = self._login("alice", USER_PASSWORD)
        bob_token = self._login("bob", USER_PASSWORD)
        channel_id = self._create_channel(admin_token, "persistent")

        channel = self._channel("bob-leave", bob_token)
        try:
            with self.assertRaises(grpc.RpcError) as non_member:
                channel_pb2_grpc.ChannelServiceStub(channel).LeaveChannel(
                    channel_pb2.ChannelMembershipRequest(
                        context=common_pb2.RequestContext(request_id="bob-leave"),
                        channel_id=channel_id,
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(non_member.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

        channel = self._channel("alice-join", alice_token)
        try:
            channel_pb2_grpc.ChannelServiceStub(channel).JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id="alice-join"),
                    channel_id=channel_id,
                ),
                timeout=2,
            )
        finally:
            channel.close()

        channel = self._channel("archive", admin_token)
        try:
            admin_pb2_grpc.AdminServiceStub(channel).ArchiveChannel(
                admin_pb2.ArchiveChannelRequest(
                    context=common_pb2.RequestContext(request_id="archive"),
                    channel_id=channel_id,
                ),
                timeout=2,
            )
        finally:
            channel.close()

        self.server.stop(0).wait()
        self.server, self.target = create_chat_server(
            self.settings, bind_address="127.0.0.1:0"
        )
        self.server.start()

        with SQLiteUnitOfWorkFactory(self.database)() as unit_of_work:
            self.assertTrue(
                unit_of_work.channels.is_member(channel_id, self._user_id("alice"))
            )
            self.assertTrue(unit_of_work.channels.get(channel_id).is_archived)

        channel = self._channel("join-archived", bob_token)
        try:
            with self.assertRaises(grpc.RpcError) as archived:
                channel_pb2_grpc.ChannelServiceStub(channel).JoinChannel(
                    channel_pb2.ChannelMembershipRequest(
                        context=common_pb2.RequestContext(request_id="join-archived"),
                        channel_id=channel_id,
                    ),
                    timeout=2,
                )
        finally:
            channel.close()
        self.assertEqual(archived.exception.code(), grpc.StatusCode.FAILED_PRECONDITION)

        channel = self._channel("admin-list", admin_token)
        try:
            listed = channel_pb2_grpc.ChannelServiceStub(channel).ListChannels(
                channel_pb2.ListChannelsRequest(
                    context=common_pb2.RequestContext(request_id="admin-list")
                ),
                timeout=2,
            )
        finally:
            channel.close()
        self.assertTrue(any(item.channel_id == channel_id and item.archived for item in listed.channels))


if __name__ == "__main__":
    unittest.main()
