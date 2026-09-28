"""Synchronous typed client used by the Tkinter interface."""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from common.grpc_metadata import MetadataClientInterceptor
from common.metadata import new_request_id
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
    llm_pb2,
    llm_pb2_grpc,
    presence_pb2,
    presence_pb2_grpc,
)


def _timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


class ChatApi:
    def __init__(self, target: str, *, timeout_seconds: float, chunk_size: int) -> None:
        self._base_channel = grpc.insecure_channel(target)
        self._timeout = timeout_seconds
        self._chunk_size = chunk_size
        self.token: str | None = None

    def close(self) -> None:
        self._base_channel.close()

    def _channel(self, request_id: str, *, authenticated: bool = True) -> grpc.Channel:
        return grpc.intercept_channel(
            self._base_channel,
            MetadataClientInterceptor(
                request_id=request_id,
                token=self.token if authenticated else None,
            ),
        )

    @staticmethod
    def _context(request_id: str, *, client_request_id: str = ""):
        return common_pb2.RequestContext(
            request_id=request_id, client_request_id=client_request_id
        )

    def login(self, username: str, password: str):
        request_id = new_request_id()
        response = auth_pb2_grpc.AuthServiceStub(
            self._channel(request_id, authenticated=False)
        ).Login(
            auth_pb2.LoginRequest(
                context=self._context(request_id), username=username, password=password
            ), timeout=self._timeout,
        )
        self.token = response.token
        return response.user

    def register(self, username: str, password: str):
        request_id = new_request_id()
        response = auth_pb2_grpc.AuthServiceStub(
            self._channel(request_id, authenticated=False)
        ).Register(
            auth_pb2.RegisterRequest(
                context=self._context(request_id), username=username, password=password
            ), timeout=self._timeout,
        )
        self.token = response.token
        return response.user

    def list_users(self):
        request_id = new_request_id()
        return auth_pb2_grpc.AuthServiceStub(self._channel(request_id)).ListUsers(
            auth_pb2.ListUsersRequest(context=self._context(request_id)),
            timeout=self._timeout,
        ).users

    def logout(self) -> None:
        if self.token is None:
            return
        request_id = new_request_id()
        try:
            auth_pb2_grpc.AuthServiceStub(self._channel(request_id)).Logout(
                auth_pb2.LogoutRequest(context=self._context(request_id)),
                timeout=self._timeout,
            )
        finally:
            self.token = None

    def list_channels(self):
        channels = []
        page_token = ""
        seen_tokens: set[str] = set()
        while True:
            request_id = new_request_id()
            response = channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).ListChannels(
                channel_pb2.ListChannelsRequest(
                    context=self._context(request_id), page_size=100,
                    page_token=page_token,
                ), timeout=self._timeout,
            )
            channels.extend(response.channels)
            page_token = response.next_page_token
            if not page_token:
                return channels
            if page_token in seen_tokens:
                raise RuntimeError("channel listing returned a repeated page token")
            seen_tokens.add(page_token)

    def create_channel(self, name: str):
        request_id = new_request_id()
        return channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).CreateChannel(
            channel_pb2.CreateChannelRequest(
                context=self._context(request_id), name=name
            ), timeout=self._timeout,
        ).channel

    def list_join_requests(self, channel_id: str):
        request_id = new_request_id()
        return channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).ListJoinRequests(
            channel_pb2.ListJoinRequestsRequest(
                context=self._context(request_id), channel_id=channel_id
            ), timeout=self._timeout,
        ).requests

    def decide_join_request(self, join_request_id: str, approve: bool) -> None:
        request_id = new_request_id()
        channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).DecideJoinRequest(
            channel_pb2.DecideJoinRequestRequest(
                context=self._context(request_id),
                join_request_id=join_request_id, approve=approve,
            ), timeout=self._timeout,
        )

    def manage_member(self, channel_id: str, user_id: str, add: bool) -> None:
        request_id = new_request_id()
        channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).ManageMember(
            channel_pb2.ManageMemberRequest(
                context=self._context(request_id),
                channel_id=channel_id, user_id=user_id, add=add,
            ), timeout=self._timeout,
        )

    def list_members(self, channel_id: str):
        request_id = new_request_id()
        return channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).ListMembers(
            channel_pb2.ListMembersRequest(
                context=self._context(request_id), channel_id=channel_id,
            ), timeout=self._timeout,
        ).members

    def delete_channel(self, channel_id: str) -> None:
        request_id = new_request_id()
        channel_pb2_grpc.ChannelServiceStub(self._channel(request_id)).DeleteChannel(
            channel_pb2.ChannelMembershipRequest(
                context=self._context(request_id), channel_id=channel_id,
            ), timeout=self._timeout,
        )

    def join_channel(self, channel_id: str) -> None:
        self._membership(channel_id, join=True)

    def leave_channel(self, channel_id: str) -> None:
        self._membership(channel_id, join=False)

    def _membership(self, channel_id: str, *, join: bool) -> None:
        request_id = new_request_id()
        stub = channel_pb2_grpc.ChannelServiceStub(self._channel(request_id))
        method = stub.JoinChannel if join else stub.LeaveChannel
        method(
            channel_pb2.ChannelMembershipRequest(
                context=self._context(request_id), channel_id=channel_id
            ), timeout=self._timeout,
        )

    def history(self, channel_id: str):
        request_id = new_request_id()
        return chat_pb2_grpc.ChatServiceStub(self._channel(request_id)).GetHistory(
            chat_pb2.GetHistoryRequest(
                context=self._context(request_id), channel_id=channel_id, page_size=100
            ), timeout=self._timeout,
        ).messages

    def send_message(self, channel_id: str, body: str):
        request_id = new_request_id()
        return chat_pb2_grpc.ChatServiceStub(self._channel(request_id)).SendMessage(
            chat_pb2.SendMessageRequest(
                context=self._context(request_id, client_request_id=str(uuid4())),
                channel_id=channel_id,
                body=body,
            ), timeout=self._timeout,
        ).message

    def subscribe_messages(self, channel_id: str):
        request_id = new_request_id()
        return chat_pb2_grpc.ChatServiceStub(self._channel(request_id)).SubscribeEvents(
            chat_pb2.SubscribeEventsRequest(
                context=self._context(request_id), channel_ids=[channel_id]
            )
        )

    def heartbeat(self) -> str:
        request_id = new_request_id()
        response = presence_pb2_grpc.PresenceServiceStub(
            self._channel(request_id)
        ).Heartbeat(
            presence_pb2.HeartbeatRequest(context=self._context(request_id)),
            timeout=self._timeout,
        )
        return response.presence

    def get_presence(self, user_id: str) -> str:
        request_id = new_request_id()
        response = presence_pb2_grpc.PresenceServiceStub(
            self._channel(request_id)
        ).GetPresence(
            presence_pb2.GetPresenceRequest(
                context=self._context(request_id), user_id=user_id,
            ), timeout=self._timeout,
        )
        return response.presence

    def upload(self, channel_id: str, path: Path):
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(self._chunk_size):
                digest.update(chunk)
        request_id = new_request_id()

        def requests():
            yield file_pb2.UploadFileRequest(
                header=file_pb2.UploadFileHeader(
                    context=self._context(request_id, client_request_id=str(uuid4())),
                    channel_id=channel_id,
                    original_name=path.name,
                    content_type=content_type,
                    expected_size_bytes=size,
                    expected_checksum_sha256=digest.hexdigest(),
                )
            )
            with path.open("rb") as source:
                while chunk := source.read(self._chunk_size):
                    yield file_pb2.UploadFileRequest(chunk=chunk)

        return file_pb2_grpc.FileServiceStub(self._channel(request_id)).UploadFile(
            requests(), timeout=max(self._timeout, 30)
        ).file

    def download(self, file_id: str, destination: Path) -> None:
        request_id = new_request_id()
        responses = file_pb2_grpc.FileServiceStub(self._channel(request_id)).DownloadFile(
            file_pb2.DownloadFileRequest(
                context=self._context(request_id), file_id=file_id
            ), timeout=max(self._timeout, 30),
        )
        digest = hashlib.sha256()
        expected = ""
        with destination.open("wb") as target:
            for response in responses:
                if response.HasField("metadata"):
                    expected = response.metadata.checksum_sha256
                elif response.HasField("chunk"):
                    target.write(response.chunk)
                    digest.update(response.chunk)
        if not expected or digest.hexdigest() != expected:
            destination.unlink(missing_ok=True)
            raise ValueError("download checksum verification failed")

    def list_files(self, channel_id: str):
        files = []
        page_token = ""
        while True:
            request_id = new_request_id()
            response = file_pb2_grpc.FileServiceStub(
                self._channel(request_id)
            ).ListChannelFiles(
                file_pb2.ListChannelFilesRequest(
                    context=self._context(request_id),
                    channel_id=channel_id,
                    page_size=100,
                    page_token=page_token,
                ),
                timeout=self._timeout,
            )
            files.extend(response.files)
            page_token = response.next_page_token
            if not page_token:
                return files

    def _assistant(self, channel_id: str, operation: str) -> tuple[str, str]:
        request_id = new_request_id()
        stub = llm_pb2_grpc.LLMServiceStub(self._channel(request_id))
        context = self._context(request_id)
        if operation == "reply":
            response = stub.GetSmartReply(
                llm_pb2.SmartReplyRequest(context=context, channel_id=channel_id),
                timeout=max(self._timeout, 35),
            )
        elif operation == "summary":
            now = datetime.now(UTC)
            response = stub.SummarizeConversation(
                llm_pb2.SummaryRequest(
                    context=context,
                    channel_id=channel_id,
                    from_time=_timestamp(now - timedelta(days=1)),
                    to_time=_timestamp(now + timedelta(seconds=1)),
                ), timeout=max(self._timeout, 35),
            )
        else:
            response = stub.GetSuggestion(
                llm_pb2.SuggestionRequest(context=context, channel_id=channel_id),
                timeout=max(self._timeout, 35),
            )
        return response.answer, response.status.message

    def smart_reply(self, channel_id: str) -> tuple[str, str]:
        return self._assistant(channel_id, "reply")

    def summary(self, channel_id: str) -> tuple[str, str]:
        return self._assistant(channel_id, "summary")

    def suggestion(self, channel_id: str) -> tuple[str, str]:
        return self._assistant(channel_id, "suggestion")
