from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc

from client.api import ChatApi
from common.config import load_settings
from common.grpc_metadata import MetadataClientInterceptor
from proto.chat.v1 import (
    auth_pb2,
    auth_pb2_grpc,
    channel_pb2,
    channel_pb2_grpc,
    chat_pb2,
    chat_pb2_grpc,
    common_pb2,
    file_pb2,
    file_pb2_grpc,
    presence_pb2,
    presence_pb2_grpc,
)
from server.database import Database
from server.grpc_server import create_chat_server
from server.repositories.sqlite import SQLiteUnitOfWorkFactory
from server.seed import seed_users


PASSWORD = "sample-password-123"
ADMIN_PASSWORD = "admin-password-123"


class Phase3CollaborationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.database = Database(root / "chat.db")
        seed_users(
            self.database,
            admin_username="admin",
            admin_password=ADMIN_PASSWORD,
            sample_usernames=["alice", "bob", "charlie", "outsider"],
            sample_password=PASSWORD,
        )
        self.upload_path = root / "uploads"
        self.settings = load_settings(
            {
                "CHAT_DATABASE_PATH": str(self.database.path),
                "FILE_STORAGE_PATH": str(self.upload_path),
                "PRESENCE_TIMEOUT_SECONDS": "0.2",
                "STREAM_KEEPALIVE_SECONDS": "0.05",
                "RPC_TIMEOUT_SECONDS": "3",
                "MAX_FILE_SIZE_BYTES": "1024",
                "FILE_CHUNK_SIZE_BYTES": "3",
            }
        )
        self.server, self.target = create_chat_server(
            self.settings, bind_address="127.0.0.1:0"
        )
        self.server.start()
        self.tokens = {
            name: self._login(name, PASSWORD)
            for name in ("alice", "bob", "charlie", "outsider")
        }
        self.channel_id = self._create_channel()
        for username in ("alice", "bob", "charlie"):
            self._join(username)

    def tearDown(self) -> None:
        self.server.stop(0).wait()
        self.directory.cleanup()

    def _channel(self, request_id: str, username: str | None = None) -> grpc.Channel:
        token = None if username is None else self.tokens[username]
        return grpc.intercept_channel(
            grpc.insecure_channel(self.target),
            MetadataClientInterceptor(request_id=request_id, token=token),
        )

    def _login(self, username: str, password: str) -> str:
        request_id = f"login-{username}-{time.time_ns()}"
        channel = grpc.intercept_channel(
            grpc.insecure_channel(self.target),
            MetadataClientInterceptor(request_id=request_id),
        )
        try:
            return auth_pb2_grpc.AuthServiceStub(channel).Login(
                auth_pb2.LoginRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    username=username,
                    password=password,
                ),
                timeout=3,
            ).token
        finally:
            channel.close()

    def _create_channel(self) -> str:
        request_id = "phase3-create"
        channel = self._channel(request_id, "alice")
        try:
            return channel_pb2_grpc.ChannelServiceStub(channel).CreateChannel(
                channel_pb2.CreateChannelRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    name="phase3-general",
                ),
                timeout=3,
            ).channel.channel_id
        finally:
            channel.close()

    def _join(self, username: str) -> None:
        if username == "alice":
            return  # The creator is already a member.
        request_id = f"join-{username}"
        channel = self._channel(request_id, username)
        try:
            channel_pb2_grpc.ChannelServiceStub(channel).JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id=request_id),
                    channel_id=self.channel_id,
                ),
                timeout=3,
            )
        finally:
            channel.close()
        owner_channel = self._channel(f"approve-{username}", "alice")
        try:
            stub = channel_pb2_grpc.ChannelServiceStub(owner_channel)
            pending = stub.ListJoinRequests(
                channel_pb2.ListJoinRequestsRequest(
                    context=common_pb2.RequestContext(request_id=f"pending-{username}"),
                    channel_id=self.channel_id,
                ), timeout=3,
            ).requests
            match = next(item for item in pending if item.user.username == username)
            stub.DecideJoinRequest(
                channel_pb2.DecideJoinRequestRequest(
                    context=common_pb2.RequestContext(request_id=f"approve-{username}"),
                    join_request_id=match.request_id,
                    approve=True,
                ), timeout=3,
            )
        finally:
            owner_channel.close()

    def _send(self, username: str, client_id: str, body: str):
        request_id = f"send-{username}-{time.time_ns()}"
        channel = self._channel(request_id, username)
        try:
            return chat_pb2_grpc.ChatServiceStub(channel).SendMessage(
                chat_pb2.SendMessageRequest(
                    context=common_pb2.RequestContext(
                        request_id=request_id, client_request_id=client_id
                    ),
                    channel_id=self.channel_id,
                    body=body,
                ),
                timeout=3,
            ).message
        finally:
            channel.close()

    def test_three_clients_concurrently_exchange_without_duplicates_and_page_history(self) -> None:
        work = [("alice", "alice-1", "from alice"),
                ("bob", "bob-1", "from bob"),
                ("charlie", "charlie-1", "from charlie")]
        with ThreadPoolExecutor(max_workers=3) as executor:
            first = list(executor.map(lambda args: self._send(*args), work))
        with ThreadPoolExecutor(max_workers=3) as executor:
            retries = list(executor.map(lambda args: self._send(*args), work))
        self.assertEqual(
            {message.message_id for message in first},
            {message.message_id for message in retries},
        )
        self.assertEqual(
            {message.sender_username for message in first},
            {"alice", "bob", "charlie"},
        )

        channel = self._channel("history-1", "alice")
        try:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            page1 = stub.GetHistory(
                chat_pb2.GetHistoryRequest(
                    context=common_pb2.RequestContext(request_id="history-1"),
                    channel_id=self.channel_id,
                    page_size=2,
                ), timeout=3,
            )
            page2 = stub.GetHistory(
                chat_pb2.GetHistoryRequest(
                    context=common_pb2.RequestContext(request_id="history-2"),
                    channel_id=self.channel_id,
                    page_size=2,
                    page_token=page1.next_page_token,
                ), timeout=3,
            )
        finally:
            channel.close()
        combined = [*page1.messages, *page2.messages]
        self.assertEqual(len(combined), 3)
        self.assertEqual(len({message.message_id for message in combined}), 3)
        self.assertEqual(
            {message.sender_username for message in combined},
            {"alice", "bob", "charlie"},
        )

    def test_message_stream_delivers_new_message_and_rejects_non_member(self) -> None:
        channel = self._channel("stream-alice", "alice")
        try:
            call = chat_pb2_grpc.ChatServiceStub(channel).SubscribeEvents(
                chat_pb2.SubscribeEventsRequest(
                    context=common_pb2.RequestContext(request_id="stream-alice"),
                    channel_ids=[self.channel_id],
                ), timeout=3,
            )
            next(call)  # establishes the subscription; normally a keepalive
            sent = self._send("bob", "stream-message", "live message")
            event = next(call)
            while event.type != chat_pb2.CHAT_EVENT_TYPE_MESSAGE:
                event = next(call)
            self.assertEqual(event.message.message_id, sent.message_id)
            self.assertEqual(event.message.sender_username, "bob")
            call.cancel()
        finally:
            channel.close()

        channel = self._channel("outsider-history", "outsider")
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                chat_pb2_grpc.ChatServiceStub(channel).GetHistory(
                    chat_pb2.GetHistoryRequest(
                        context=common_pb2.RequestContext(request_id="outsider-history"),
                        channel_id=self.channel_id,
                    ), timeout=3,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_presence_stream_reports_online_then_timeout_offline(self) -> None:
        channel = self._channel("presence-stream", "alice")
        try:
            call = presence_pb2_grpc.PresenceServiceStub(channel).SubscribePresence(
                presence_pb2.SubscribePresenceRequest(
                    context=common_pb2.RequestContext(request_id="presence-stream")
                ), timeout=3,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(next, call)
                time.sleep(0.08)
                bob_channel = self._channel("bob-heartbeat", "bob")
                try:
                    presence_pb2_grpc.PresenceServiceStub(bob_channel).Heartbeat(
                        presence_pb2.HeartbeatRequest(
                            context=common_pb2.RequestContext(request_id="bob-heartbeat")
                        ), timeout=3,
                    )
                finally:
                    bob_channel.close()
                online = pending.result(timeout=2)
            self.assertEqual(online.presence, "online")
            offline = next(call)
            self.assertEqual(offline.user_id, online.user_id)
            self.assertEqual(offline.presence, "offline")
            call.cancel()
        finally:
            channel.close()

    def test_presence_snapshot_reports_online_then_offline(self) -> None:
        observer = ChatApi(self.target, timeout_seconds=3, chunk_size=3)
        observed = ChatApi(self.target, timeout_seconds=3, chunk_size=3)
        observer.token = self.tokens["alice"]
        observed.token = self.tokens["bob"]
        try:
            observed.heartbeat()
            bob_id = self._user_id("bob")
            self.assertEqual(observer.get_presence(bob_id), "online")
            time.sleep(0.35)
            self.assertEqual(observer.get_presence(bob_id), "offline")
        finally:
            observer.close()
            observed.close()

    @staticmethod
    def _upload_requests(channel_id: str, request_id: str, client_id: str,
                         content: bytes, checksum: str, expected_size: int | None = None):
        yield file_pb2.UploadFileRequest(
            header=file_pb2.UploadFileHeader(
                context=common_pb2.RequestContext(
                    request_id=request_id, client_request_id=client_id
                ),
                channel_id=channel_id,
                original_name="notes.txt",
                content_type="text/plain",
                expected_size_bytes=len(content) if expected_size is None else expected_size,
                expected_checksum_sha256=checksum,
            )
        )
        for offset in range(0, len(content), 3):
            yield file_pb2.UploadFileRequest(chunk=content[offset:offset + 3])

    def test_chunked_file_checksum_idempotency_and_authorization(self) -> None:
        content = b"phase three file bytes"
        checksum = hashlib.sha256(content).hexdigest()
        request_id = "upload-valid"
        channel = self._channel(request_id, "alice")
        try:
            stub = file_pb2_grpc.FileServiceStub(channel)
            uploaded = stub.UploadFile(
                self._upload_requests(
                    self.channel_id, request_id, "file-operation-1", content, checksum
                ), timeout=3,
            ).file
            duplicate = stub.UploadFile(
                self._upload_requests(
                    self.channel_id, "upload-retry", "file-operation-1", content, checksum
                ), timeout=3,
            ).file
            self.assertEqual(uploaded.file_id, duplicate.file_id)
            self.assertEqual(uploaded.uploader_username, "alice")
            responses = list(stub.DownloadFile(
                file_pb2.DownloadFileRequest(
                    context=common_pb2.RequestContext(request_id="download-valid"),
                    file_id=uploaded.file_id,
                ), timeout=3,
            ))
        finally:
            channel.close()
        downloaded = b"".join(item.chunk for item in responses if item.HasField("chunk"))
        self.assertEqual(downloaded, content)
        self.assertEqual(hashlib.sha256(downloaded).hexdigest(), uploaded.checksum_sha256)

        channel = self._channel("outsider-download", "outsider")
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                list(file_pb2_grpc.FileServiceStub(channel).DownloadFile(
                    file_pb2.DownloadFileRequest(
                        context=common_pb2.RequestContext(request_id="outsider-download"),
                        file_id=uploaded.file_id,
                    ), timeout=3,
                ))
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_files_are_paginated_and_streamed_only_to_channel_members(self) -> None:
        stream_channel = self._channel("file-stream", "alice")
        stream = chat_pb2_grpc.ChatServiceStub(stream_channel).SubscribeEvents(
            chat_pb2.SubscribeEventsRequest(
                context=common_pb2.RequestContext(request_id="file-stream"),
                channel_ids=[self.channel_id],
            ), timeout=3,
        )
        next(stream)
        uploaded = []
        for index, content in enumerate((b"first attachment", b"second attachment"), 1):
            checksum = hashlib.sha256(content).hexdigest()
            channel = self._channel(f"upload-list-{index}", "bob")
            try:
                uploaded.append(
                    file_pb2_grpc.FileServiceStub(channel).UploadFile(
                        self._upload_requests(
                            self.channel_id,
                            f"upload-list-{index}",
                            f"file-list-{index}",
                            content,
                            checksum,
                        ), timeout=3,
                    ).file
                )
            finally:
                channel.close()

        event = next(stream)
        while event.type != chat_pb2.CHAT_EVENT_TYPE_FILE:
            event = next(stream)
        self.assertIn(event.file.file_id, {item.file_id for item in uploaded})
        self.assertEqual(event.file.uploader_username, "bob")
        stream.cancel()
        stream_channel.close()

        channel = self._channel("list-files-1", "alice")
        try:
            stub = file_pb2_grpc.FileServiceStub(channel)
            first = stub.ListChannelFiles(
                file_pb2.ListChannelFilesRequest(
                    context=common_pb2.RequestContext(request_id="list-files-1"),
                    channel_id=self.channel_id,
                    page_size=1,
                ), timeout=3,
            )
            second = stub.ListChannelFiles(
                file_pb2.ListChannelFilesRequest(
                    context=common_pb2.RequestContext(request_id="list-files-2"),
                    channel_id=self.channel_id,
                    page_size=1,
                    page_token=first.next_page_token,
                ), timeout=3,
            )
        finally:
            channel.close()
        self.assertTrue(first.next_page_token)
        listed = [*first.files, *second.files]
        self.assertEqual(
            {item.file_id for item in listed}, {item.file_id for item in uploaded}
        )
        self.assertEqual({item.uploader_username for item in listed}, {"bob"})

        channel = self._channel("outsider-list-files", "outsider")
        try:
            with self.assertRaises(grpc.RpcError) as captured:
                file_pb2_grpc.FileServiceStub(channel).ListChannelFiles(
                    file_pb2.ListChannelFilesRequest(
                        context=common_pb2.RequestContext(
                            request_id="outsider-list-files"
                        ),
                        channel_id=self.channel_id,
                    ), timeout=3,
                )
        finally:
            channel.close()
        self.assertEqual(captured.exception.code(), grpc.StatusCode.PERMISSION_DENIED)

    def test_interrupted_and_bad_checksum_uploads_leave_no_partial_files(self) -> None:
        content = b"incomplete"
        good_checksum = hashlib.sha256(content).hexdigest()
        channel = self._channel("upload-interrupted", "alice")
        try:
            stub = file_pb2_grpc.FileServiceStub(channel)
            with self.assertRaises(grpc.RpcError) as interrupted:
                stub.UploadFile(
                    self._upload_requests(
                        self.channel_id, "upload-interrupted", "interrupted-1",
                        content, good_checksum, expected_size=len(content) + 1,
                    ), timeout=3,
                )
            with self.assertRaises(grpc.RpcError) as invalid:
                stub.UploadFile(
                    self._upload_requests(
                        self.channel_id, "upload-bad-checksum", "checksum-1",
                        content, "0" * 64,
                    ), timeout=3,
                )
        finally:
            channel.close()
        self.assertEqual(interrupted.exception.code(), grpc.StatusCode.INVALID_ARGUMENT)
        self.assertEqual(invalid.exception.code(), grpc.StatusCode.INVALID_ARGUMENT)
        self.assertEqual(list(self.upload_path.iterdir()), [])

    def test_removed_member_loses_existing_event_stream(self) -> None:
        channel = self._channel("bob-stream-before-removal", "bob")
        stream = chat_pb2_grpc.ChatServiceStub(channel).SubscribeEvents(
            chat_pb2.SubscribeEventsRequest(
                context=common_pb2.RequestContext(request_id="bob-stream-before-removal"),
                channel_ids=[self.channel_id],
            ), timeout=3,
        )
        try:
            next(stream)  # subscription is established
            owner_channel = self._channel("remove-bob-stream", "alice")
            try:
                channel_pb2_grpc.ChannelServiceStub(owner_channel).ManageMember(
                    channel_pb2.ManageMemberRequest(
                        context=common_pb2.RequestContext(request_id="remove-bob-stream"),
                        channel_id=self.channel_id,
                        user_id=self._user_id("bob"),
                        add=False,
                    ), timeout=3,
                )
            finally:
                owner_channel.close()
            with self.assertRaises(grpc.RpcError) as revoked:
                for _ in range(20):
                    next(stream)
            self.assertEqual(revoked.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        finally:
            stream.cancel()
            channel.close()

    def test_only_owner_can_delete_channel_and_children_are_erased(self) -> None:
        content = b"channel to delete"
        self._send("alice", "before-delete", "this will be removed")
        connection = self._channel("upload-before-delete", "alice")
        try:
            uploaded = file_pb2_grpc.FileServiceStub(connection).UploadFile(
                self._upload_requests(
                    self.channel_id, "upload-before-delete", "upload-before-delete",
                    content, hashlib.sha256(content).hexdigest(),
                ), timeout=3,
            ).file
        finally:
            connection.close()
        outsider_channel = self._channel("pending-before-delete", "outsider")
        try:
            channel_pb2_grpc.ChannelServiceStub(outsider_channel).JoinChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id="pending-before-delete"),
                    channel_id=self.channel_id,
                ), timeout=3,
            )
        finally:
            outsider_channel.close()
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            storage_reference = unit.files.get(uploaded.file_id).storage_reference
        other_channel_id = self._create_other_channel()
        member_channel = self._channel("member-delete-denied", "bob")
        try:
            with self.assertRaises(grpc.RpcError) as denied:
                channel_pb2_grpc.ChannelServiceStub(member_channel).DeleteChannel(
                    channel_pb2.ChannelMembershipRequest(
                        context=common_pb2.RequestContext(request_id="member-delete-denied"),
                        channel_id=self.channel_id,
                    ), timeout=3,
                )
        finally:
            member_channel.close()
        self.assertEqual(denied.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        anonymous_channel = self._channel("anonymous-delete")
        try:
            with self.assertRaises(grpc.RpcError) as anonymous:
                channel_pb2_grpc.ChannelServiceStub(anonymous_channel).DeleteChannel(
                    channel_pb2.ChannelMembershipRequest(
                        context=common_pb2.RequestContext(request_id="anonymous-delete"),
                        channel_id=self.channel_id,
                    ), timeout=3,
                )
        finally:
            anonymous_channel.close()
        self.assertEqual(anonymous.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        owner_channel = self._channel("owner-delete", "alice")
        try:
            channel_pb2_grpc.ChannelServiceStub(owner_channel).DeleteChannel(
                channel_pb2.ChannelMembershipRequest(
                    context=common_pb2.RequestContext(request_id="owner-delete"),
                    channel_id=self.channel_id,
                ), timeout=3,
            )
        finally:
            owner_channel.close()
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            self.assertIsNone(unit.channels.get(self.channel_id))
            self.assertIsNotNone(unit.channels.get(other_channel_id))
            for table in ("channel_members", "channel_join_requests", "messages", "files"):
                self.assertEqual(unit.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE channel_id=?", (self.channel_id,)
                ).fetchone()[0], 0)
            self.assertIsNotNone(unit.users.get(self._user_id("bob")))
        self.assertTrue((self.upload_path / storage_reference).exists())
        member_channel = self._channel("after-delete", "bob")
        try:
            with self.assertRaises(grpc.RpcError) as history_missing:
                chat_pb2_grpc.ChatServiceStub(member_channel).GetHistory(
                    chat_pb2.GetHistoryRequest(
                        context=common_pb2.RequestContext(request_id="after-delete-history"),
                        channel_id=self.channel_id,
                    ), timeout=3,
                )
            with self.assertRaises(grpc.RpcError) as file_missing:
                list(file_pb2_grpc.FileServiceStub(member_channel).DownloadFile(
                    file_pb2.DownloadFileRequest(
                        context=common_pb2.RequestContext(request_id="after-delete-file"),
                        file_id=uploaded.file_id,
                    ), timeout=3,
                ))
        finally:
            member_channel.close()
        self.assertEqual(history_missing.exception.code(), grpc.StatusCode.NOT_FOUND)
        self.assertEqual(file_missing.exception.code(), grpc.StatusCode.NOT_FOUND)
        self.server.stop(0).wait()
        self.server, self.target = create_chat_server(self.settings, bind_address="127.0.0.1:0")
        self.server.start()
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            self.assertIsNone(unit.channels.get(self.channel_id))
            self.assertIsNotNone(unit.channels.get(other_channel_id))

    def _user_id(self, username: str) -> str:
        with SQLiteUnitOfWorkFactory(self.database)() as unit:
            return unit.users.get_by_username(username).user.id

    def _create_other_channel(self) -> str:
        connection = self._channel("create-other", "alice")
        try:
            return channel_pb2_grpc.ChannelServiceStub(connection).CreateChannel(
                channel_pb2.CreateChannelRequest(
                    context=common_pb2.RequestContext(request_id="create-other"),
                    name="other-channel",
                ), timeout=3,
            ).channel.channel_id
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
