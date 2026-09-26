from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc

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
            name: self._login(name, ADMIN_PASSWORD if name == "admin" else PASSWORD)
            for name in ("admin", "alice", "bob", "charlie", "outsider")
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
        channel = self._channel(request_id, "admin")
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


if __name__ == "__main__":
    unittest.main()
