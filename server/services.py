"""Typed Phase 1 chat-side gRPC service skeletons."""

from __future__ import annotations

import time
from collections.abc import Iterator

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from common.grpc_metadata import get_auth_token, get_request_id
from common.metadata import new_request_id, utc_now
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
    file_pb2,
    file_pb2_grpc,
    health_pb2,
    health_pb2_grpc,
    presence_pb2,
    presence_pb2_grpc,
)
from server.validation import abort_invalid, abort_unimplemented, require_request_id, require_text


def _timestamp_now() -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(utc_now())
    return timestamp


class HealthService(health_pb2_grpc.HealthServiceServicer):
    def __init__(self, *, service_name: str, node_id: str) -> None:
        self._service_name = service_name
        self._node_id = node_id

    def Check(
        self, request: health_pb2.HealthCheckRequest, context: grpc.ServicerContext
    ) -> health_pb2.HealthCheckResponse:
        request_id = require_request_id(request.context, context)
        context.set_trailing_metadata((("x-request-id", request_id),))
        return health_pb2.HealthCheckResponse(
            status=common_pb2.ResponseStatus(
                code=common_pb2.STATUS_CODE_OK,
                message="serving",
                request_id=request_id,
            ),
            service=self._service_name,
            node_id=self._node_id,
            serving=True,
            auth_metadata_present=get_auth_token() is not None,
        )


class AuthService(auth_pb2_grpc.AuthServiceServicer):
    def Login(
        self, request: auth_pb2.LoginRequest, context: grpc.ServicerContext
    ) -> auth_pb2.LoginResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.username, "username", request_id, context)
        require_text(request.password, "password", request_id, context)
        abort_unimplemented(context, request_id, "AuthService.Login")

    def Logout(
        self, request: auth_pb2.LogoutRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        abort_unimplemented(context, request_id, "AuthService.Logout")


class ChannelService(channel_pb2_grpc.ChannelServiceServicer):
    def CreateChannel(
        self, request: channel_pb2.CreateChannelRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ChannelResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.name, "name", request_id, context)
        abort_unimplemented(context, request_id, "ChannelService.CreateChannel")

    def ListChannels(
        self, request: channel_pb2.ListChannelsRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ListChannelsResponse:
        request_id = require_request_id(request.context, context)
        if request.page_size < 0:
            abort_invalid(context, request_id, "page_size must not be negative")
        abort_unimplemented(context, request_id, "ChannelService.ListChannels")

    def JoinChannel(
        self, request: channel_pb2.ChannelMembershipRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "ChannelService.JoinChannel")

    def LeaveChannel(
        self, request: channel_pb2.ChannelMembershipRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "ChannelService.LeaveChannel")


class ChatService(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self, *, keepalive_seconds: float) -> None:
        self._keepalive_seconds = keepalive_seconds

    def SendMessage(
        self, request: chat_pb2.SendMessageRequest, context: grpc.ServicerContext
    ) -> chat_pb2.SendMessageResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.context.client_request_id, "context.client_request_id", request_id, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        require_text(request.body, "body", request_id, context)
        abort_unimplemented(context, request_id, "ChatService.SendMessage")

    def GetHistory(
        self, request: chat_pb2.GetHistoryRequest, context: grpc.ServicerContext
    ) -> chat_pb2.GetHistoryResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        if request.page_size < 0:
            abort_invalid(context, request_id, "page_size must not be negative")
        abort_unimplemented(context, request_id, "ChatService.GetHistory")

    def SubscribeEvents(
        self, request: chat_pb2.SubscribeEventsRequest, context: grpc.ServicerContext
    ) -> Iterator[chat_pb2.ChatEvent]:
        request_id = require_request_id(request.context, context)
        if not request.channel_ids:
            abort_invalid(context, request_id, "at least one channel_id is required")
        if any(not channel_id.strip() for channel_id in request.channel_ids):
            abort_invalid(context, request_id, "channel_ids must not contain empty values")

        context.set_trailing_metadata((("x-request-id", request_id),))
        while context.is_active():
            yield chat_pb2.ChatEvent(
                event_id=new_request_id(),
                type=chat_pb2.CHAT_EVENT_TYPE_KEEPALIVE,
                occurred_at=_timestamp_now(),
                request_id=get_request_id() or request_id,
            )
            time.sleep(self._keepalive_seconds)


class PresenceService(presence_pb2_grpc.PresenceServiceServicer):
    def Heartbeat(
        self, request: presence_pb2.HeartbeatRequest, context: grpc.ServicerContext
    ) -> presence_pb2.PresenceResponse:
        request_id = require_request_id(request.context, context)
        abort_unimplemented(context, request_id, "PresenceService.Heartbeat")

    def GetPresence(
        self, request: presence_pb2.GetPresenceRequest, context: grpc.ServicerContext
    ) -> presence_pb2.PresenceResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        abort_unimplemented(context, request_id, "PresenceService.GetPresence")

    def SubscribePresence(
        self,
        request: presence_pb2.SubscribePresenceRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[presence_pb2.PresenceEvent]:
        request_id = require_request_id(request.context, context)
        abort_unimplemented(context, request_id, "PresenceService.SubscribePresence")
        yield  # pragma: no cover - keeps this method a streaming generator


class FileService(file_pb2_grpc.FileServiceServicer):
    def UploadFile(
        self,
        request_iterator: Iterator[file_pb2.UploadFileRequest],
        context: grpc.ServicerContext,
    ) -> file_pb2.UploadFileResponse:
        first_request = next(request_iterator, None)
        if first_request is None or not first_request.HasField("header"):
            abort_invalid(context, get_request_id(), "first upload item must contain a header")
        request_id = require_request_id(first_request.header.context, context)
        require_text(first_request.header.channel_id, "channel_id", request_id, context)
        require_text(first_request.header.original_name, "original_name", request_id, context)
        abort_unimplemented(context, request_id, "FileService.UploadFile")

    def DownloadFile(
        self, request: file_pb2.DownloadFileRequest, context: grpc.ServicerContext
    ) -> Iterator[file_pb2.DownloadFileResponse]:
        request_id = require_request_id(request.context, context)
        require_text(request.file_id, "file_id", request_id, context)
        abort_unimplemented(context, request_id, "FileService.DownloadFile")
        yield  # pragma: no cover - keeps this method a streaming generator


class AdminService(admin_pb2_grpc.AdminServiceServicer):
    def CreateUser(
        self, request: admin_pb2.CreateUserRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.username, "username", request_id, context)
        require_text(request.password, "password", request_id, context)
        require_text(request.role, "role", request_id, context)
        abort_unimplemented(context, request_id, "AdminService.CreateUser")

    def SetUserStatus(
        self, request: admin_pb2.SetUserStatusRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        require_text(request.status, "status", request_id, context)
        abort_unimplemented(context, request_id, "AdminService.SetUserStatus")

    def SetUserRole(
        self, request: admin_pb2.SetUserRoleRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        require_text(request.role, "role", request_id, context)
        abort_unimplemented(context, request_id, "AdminService.SetUserRole")

    def ArchiveChannel(
        self, request: admin_pb2.ArchiveChannelRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ChannelResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "AdminService.ArchiveChannel")

    def ManageChannelMember(
        self,
        request: admin_pb2.ManageChannelMemberRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        require_text(request.user_id, "user_id", request_id, context)
        abort_unimplemented(context, request_id, "AdminService.ManageChannelMember")

