"""Owner-based registration and channel authorization integration tests."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc

from common.config import load_settings
from common.grpc_metadata import MetadataClientInterceptor
from domain.models import UserStatus
from proto.chat.v1 import (admin_pb2, admin_pb2_grpc, auth_pb2, auth_pb2_grpc,
                           channel_pb2, channel_pb2_grpc, chat_pb2, chat_pb2_grpc,
                           common_pb2)
from server.database import Database
from server.grpc_server import create_chat_server
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


PASSWORD = "sample-password-123"


class Phase2AccessIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "chat.db")
        self.settings = load_settings({"CHAT_DATABASE_PATH": str(self.database.path),
                                       "RPC_TIMEOUT_SECONDS": "2"})
        self.server, self.target = create_chat_server(self.settings, bind_address="127.0.0.1:0")
        self.server.start()
        self.tokens: dict[str, str] = {}
        self.ids: dict[str, str] = {}
        for name in ("alice", "bob", "charlie"):
            self.register(name)

    def tearDown(self) -> None:
        self.server.stop(0).wait()
        self.directory.cleanup()

    def channel(self, name: str | None = None):
        return grpc.intercept_channel(grpc.insecure_channel(self.target),
            MetadataClientInterceptor(request_id="metadata-test", token=self.tokens.get(name or "")))

    def register(self, name: str) -> None:
        with self.channel() as connection:
            result = auth_pb2_grpc.AuthServiceStub(connection).Register(
                auth_pb2.RegisterRequest(context=common_pb2.RequestContext(request_id=f"register-{name}"),
                    username=name, password=PASSWORD), timeout=2)
        self.tokens[name] = result.token
        self.ids[name] = result.user.user_id
        self.assertEqual(result.user.role, "user")

    def create(self, owner: str = "alice", name: str = "general") -> str:
        with self.channel(owner) as connection:
            result = channel_pb2_grpc.ChannelServiceStub(connection).CreateChannel(
                channel_pb2.CreateChannelRequest(
                    context=common_pb2.RequestContext(request_id=f"create-{name}"), name=name), timeout=2)
        self.assertEqual(result.channel.owner_id, self.ids[owner])
        self.assertTrue(result.channel.is_member)
        return result.channel.channel_id

    def join(self, name: str, channel_id: str) -> None:
        with self.channel(name) as connection:
            result = channel_pb2_grpc.ChannelServiceStub(connection).JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id=f"join-{name}"),
                    channel_id=channel_id), timeout=2)
        self.assertIn("pending", result.status.message)

    def pending(self, owner: str, channel_id: str):
        with self.channel(owner) as connection:
            return channel_pb2_grpc.ChannelServiceStub(connection).ListJoinRequests(
                channel_pb2.ListJoinRequestsRequest(
                    context=common_pb2.RequestContext(request_id="list-pending"),
                    channel_id=channel_id), timeout=2).requests

    def decide(self, owner: str, join_id: str, approve: bool) -> None:
        with self.channel(owner) as connection:
            channel_pb2_grpc.ChannelServiceStub(connection).DecideJoinRequest(
                channel_pb2.DecideJoinRequestRequest(
                    context=common_pb2.RequestContext(request_id="decide-request"),
                    join_request_id=join_id, approve=approve), timeout=2)

    def test_registration_user_list_approval_and_logout(self) -> None:
        channel_id = self.create()
        with self.channel("bob") as connection:
            users = auth_pb2_grpc.AuthServiceStub(connection).ListUsers(
                auth_pb2.ListUsersRequest(context=common_pb2.RequestContext(request_id="users")),
                timeout=2).users
            listed = channel_pb2_grpc.ChannelServiceStub(connection).ListChannels(
                channel_pb2.ListChannelsRequest(context=common_pb2.RequestContext(request_id="channels")),
                timeout=2).channels
        self.assertEqual([user.username for user in users], ["alice", "bob", "charlie"])
        self.assertEqual(len(listed), 1)
        self.assertFalse(listed[0].is_member)
        self.join("bob", channel_id)
        self.join("bob", channel_id)
        pending = self.pending("alice", channel_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].user.username, "bob")
        self.decide("alice", pending[0].request_id, True)
        self.decide("alice", pending[0].request_id, True)
        with self.channel("bob") as connection:
            self.assertTrue(channel_pb2_grpc.ChannelServiceStub(connection).ListChannels(
                channel_pb2.ListChannelsRequest(
                    context=common_pb2.RequestContext(request_id="after-approval")), timeout=2
            ).channels[0].is_member)
            auth_pb2_grpc.AuthServiceStub(connection).Logout(
                auth_pb2.LogoutRequest(context=common_pb2.RequestContext(request_id="logout")), timeout=2)
            with self.assertRaises(grpc.RpcError) as error:
                auth_pb2_grpc.AuthServiceStub(connection).ListUsers(
                    auth_pb2.ListUsersRequest(context=common_pb2.RequestContext(request_id="after-logout")),
                    timeout=2)
        self.assertEqual(error.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

    def test_owner_permissions_nonmember_and_retired_admin_rpc(self) -> None:
        channel_id = self.create()
        self.join("bob", channel_id)
        join_id = self.pending("alice", channel_id)[0].request_id
        with self.channel("charlie") as connection:
            channels = channel_pb2_grpc.ChannelServiceStub(connection)
            for call in (
                lambda: channels.ListJoinRequests(channel_pb2.ListJoinRequestsRequest(
                    context=common_pb2.RequestContext(request_id="not-owner-list"), channel_id=channel_id), timeout=2),
                lambda: channels.DecideJoinRequest(channel_pb2.DecideJoinRequestRequest(
                    context=common_pb2.RequestContext(request_id="not-owner-decide"),
                    join_request_id=join_id, approve=True), timeout=2),
                lambda: channels.ManageMember(channel_pb2.ManageMemberRequest(
                    context=common_pb2.RequestContext(request_id="not-owner-manage"),
                    channel_id=channel_id, user_id=self.ids["charlie"], add=True), timeout=2),
                lambda: chat_pb2_grpc.ChatServiceStub(connection).GetHistory(chat_pb2.GetHistoryRequest(
                    context=common_pb2.RequestContext(request_id="not-member-history"),
                    channel_id=channel_id), timeout=2),
                lambda: chat_pb2_grpc.ChatServiceStub(connection).SendMessage(chat_pb2.SendMessageRequest(
                    context=common_pb2.RequestContext(request_id="not-member-send",
                        client_request_id="not-member-send"), channel_id=channel_id, body="no"), timeout=2),
            ):
                with self.assertRaises(grpc.RpcError) as error:
                    call()
                self.assertEqual(error.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
            with self.assertRaises(grpc.RpcError) as retired:
                admin_pb2_grpc.AdminServiceStub(connection).CreateUser(
                    admin_pb2.CreateUserRequest(
                        context=common_pb2.RequestContext(request_id="old-admin"),
                        username="mallory", password=PASSWORD, role="user"), timeout=2)
        self.assertEqual(retired.exception.code(), grpc.StatusCode.UNIMPLEMENTED)

    def test_rejection_removal_and_restart(self) -> None:
        channel_id = self.create()
        self.join("bob", channel_id)
        self.decide("alice", self.pending("alice", channel_id)[0].request_id, False)
        self.assertFalse(self.pending("alice", channel_id))
        self.join("bob", channel_id)
        self.decide("alice", self.pending("alice", channel_id)[0].request_id, True)
        with self.channel("alice") as connection:
            channels = channel_pb2_grpc.ChannelServiceStub(connection)
            channels.ManageMember(channel_pb2.ManageMemberRequest(
                context=common_pb2.RequestContext(request_id="remove-bob"),
                channel_id=channel_id, user_id=self.ids["bob"], add=False), timeout=2)
            with self.assertRaises(grpc.RpcError) as error:
                channels.ManageMember(channel_pb2.ManageMemberRequest(
                    context=common_pb2.RequestContext(request_id="remove-owner"),
                    channel_id=channel_id, user_id=self.ids["alice"], add=False), timeout=2)
        self.assertEqual(error.exception.code(), grpc.StatusCode.FAILED_PRECONDITION)
        self.server.stop(0).wait()
        self.server, self.target = create_chat_server(self.settings, bind_address="127.0.0.1:0")
        self.server.start()
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            self.assertFalse(unit.channels.is_member(channel_id, self.ids["bob"]))
            self.assertTrue(unit.channels.is_member(channel_id, self.ids["alice"]))
        self.join("bob", channel_id)
        self.assertEqual(len(self.pending("alice", channel_id)), 1)

    def test_invalid_token_disabled_user_and_duplicate_registration(self) -> None:
        with self.channel() as connection:
            with self.assertRaises(grpc.RpcError) as invalid:
                auth_pb2_grpc.AuthServiceStub(connection).ListUsers(
                    auth_pb2.ListUsersRequest(context=common_pb2.RequestContext(request_id="invalid")), timeout=2)
            with self.assertRaises(grpc.RpcError) as duplicate:
                auth_pb2_grpc.AuthServiceStub(connection).Register(auth_pb2.RegisterRequest(
                    context=common_pb2.RequestContext(request_id="duplicate"),
                    username="ALICE", password=PASSWORD), timeout=2)
        self.assertEqual(invalid.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        self.assertEqual(duplicate.exception.code(), grpc.StatusCode.ALREADY_EXISTS)
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            unit.users.set_status(self.ids["bob"], UserStatus.DISABLED)
            unit.commit()
        with self.channel("bob") as connection:
            with self.assertRaises(grpc.RpcError) as disabled:
                auth_pb2_grpc.AuthServiceStub(connection).ListUsers(
                    auth_pb2.ListUsersRequest(context=common_pb2.RequestContext(request_id="disabled")), timeout=2)
        self.assertEqual(disabled.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_concurrent_join_requests_are_deduplicated(self) -> None:
        channel_id = self.create()
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _: self.join("bob", channel_id), range(5)))
        self.assertEqual(len(self.pending("alice", channel_id)), 1)

    def test_members_can_see_roster_but_only_owner_can_remove(self) -> None:
        channel_id = self.create()
        self.join("bob", channel_id)
        self.decide("alice", self.pending("alice", channel_id)[0].request_id, True)
        with self.channel("bob") as connection:
            stub = channel_pb2_grpc.ChannelServiceStub(connection)
            members = stub.ListMembers(channel_pb2.ListMembersRequest(
                context=common_pb2.RequestContext(request_id="bob-roster"),
                channel_id=channel_id), timeout=2).members
            self.assertEqual([user.username for user in members], ["alice", "bob"])
            with self.assertRaises(grpc.RpcError) as denied:
                stub.ManageMember(channel_pb2.ManageMemberRequest(
                    context=common_pb2.RequestContext(request_id="bob-remove"),
                    channel_id=channel_id, user_id=self.ids["alice"], add=False), timeout=2)
        self.assertEqual(denied.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        with self.channel("charlie") as connection:
            with self.assertRaises(grpc.RpcError) as outsider:
                channel_pb2_grpc.ChannelServiceStub(connection).ListMembers(
                    channel_pb2.ListMembersRequest(
                        context=common_pb2.RequestContext(request_id="outsider-roster"),
                        channel_id=channel_id), timeout=2)
        self.assertEqual(outsider.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        with self.channel("alice") as connection:
            channel_pb2_grpc.ChannelServiceStub(connection).ManageMember(
                channel_pb2.ManageMemberRequest(
                    context=common_pb2.RequestContext(request_id="owner-remove-bob"),
                    channel_id=channel_id, user_id=self.ids["bob"], add=False), timeout=2)
        with self.channel("bob") as connection:
            with self.assertRaises(grpc.RpcError) as former_member:
                channel_pb2_grpc.ChannelServiceStub(connection).ListMembers(
                    channel_pb2.ListMembersRequest(
                        context=common_pb2.RequestContext(request_id="removed-roster"),
                        channel_id=channel_id), timeout=2)
        self.assertEqual(former_member.exception.code(), grpc.StatusCode.PERMISSION_DENIED)


if __name__ == "__main__":
    unittest.main()
