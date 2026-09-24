"""Typed Phase 1 chat-side gRPC service skeletons."""

from __future__ import annotations

import time
from collections.abc import Iterator

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from common.errors import ApplicationError
from common.grpc_metadata import get_auth_token, get_request_id
from common.metadata import new_request_id, utc_now
from domain.models import Channel, User
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
from server.application.admin import AdminApplication
from server.application.auth import AuthApplication
from server.application.channels import ChannelApplication
from server.validation import (
    abort_application_error,
    abort_invalid,
    abort_unimplemented,
    require_request_id,
    require_text,
)


def _timestamp_now() -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(utc_now())
    return timestamp


def _timestamp(value: object) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _ok_status(request_id: str, message: str = "ok") -> common_pb2.ResponseStatus:
    return common_pb2.ResponseStatus(
        code=common_pb2.STATUS_CODE_OK,
        message=message,
        request_id=request_id,
    )


def _user_summary(user: User) -> common_pb2.UserSummary:
    return common_pb2.UserSummary(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        status=user.status.value,
    )


def _channel_summary(channel: Channel) -> common_pb2.ChannelSummary:
    return common_pb2.ChannelSummary(
        channel_id=channel.id,
        name=channel.name,
        archived=channel.is_archived,
    )


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
    def __init__(self, application: AuthApplication) -> None:
        self._application = application

    def Login(
        self, request: auth_pb2.LoginRequest, context: grpc.ServicerContext
    ) -> auth_pb2.LoginResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.username, "username", request_id, context)
        require_text(request.password, "password", request_id, context)
        try:
            result = self._application.login(
                request.username, request.password, request_id=request_id
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return auth_pb2.LoginResponse(
            status=_ok_status(request_id, "login successful"),
            token=result.token,
            expires_at=_timestamp(result.expires_at),
        )

    def Logout(
        self, request: auth_pb2.LogoutRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        try:
            self._application.logout(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return common_pb2.EmptyResponse(status=_ok_status(request_id, "logout successful"))


class ChannelService(channel_pb2_grpc.ChannelServiceServicer):
    def __init__(self, application: ChannelApplication) -> None:
        self._application = application

    def CreateChannel(
        self, request: channel_pb2.CreateChannelRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ChannelResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.name, "name", request_id, context)
        try:
            channel = self._application.create_channel(
                get_auth_token(), request.name, request_id=request_id
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return channel_pb2.ChannelResponse(
            status=_ok_status(request_id, "channel created"),
            channel=_channel_summary(channel),
        )

    def ListChannels(
        self, request: channel_pb2.ListChannelsRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ListChannelsResponse:
        request_id = require_request_id(request.context, context)
        if request.page_size < 0:
            abort_invalid(context, request_id, "page_size must not be negative")
        try:
            page = self._application.list_channels(
                get_auth_token(),
                request.page_size,
                request.page_token,
                request_id=request_id,
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return channel_pb2.ListChannelsResponse(
            status=_ok_status(request_id),
            channels=[_channel_summary(channel) for channel in page.channels],
            next_page_token=page.next_page_token,
        )

    def JoinChannel(
        self, request: channel_pb2.ChannelMembershipRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        try:
            self._application.join_channel(
                get_auth_token(), request.channel_id, request_id=request_id
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return common_pb2.EmptyResponse(status=_ok_status(request_id, "channel joined"))

    def LeaveChannel(
        self, request: channel_pb2.ChannelMembershipRequest, context: grpc.ServicerContext
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        try:
            self._application.leave_channel(
                get_auth_token(), request.channel_id, request_id=request_id
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return common_pb2.EmptyResponse(status=_ok_status(request_id, "channel left"))


class ChatService(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self, auth: AuthApplication, *, keepalive_seconds: float) -> None:
        self._auth = auth
        self._keepalive_seconds = keepalive_seconds

    def SendMessage(
        self, request: chat_pb2.SendMessageRequest, context: grpc.ServicerContext
    ) -> chat_pb2.SendMessageResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.context.client_request_id, "context.client_request_id", request_id, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        require_text(request.body, "body", request_id, context)
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "ChatService.SendMessage")

    def GetHistory(
        self, request: chat_pb2.GetHistoryRequest, context: grpc.ServicerContext
    ) -> chat_pb2.GetHistoryResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        if request.page_size < 0:
            abort_invalid(context, request_id, "page_size must not be negative")
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "ChatService.GetHistory")

    def SubscribeEvents(
        self, request: chat_pb2.SubscribeEventsRequest, context: grpc.ServicerContext
    ) -> Iterator[chat_pb2.ChatEvent]:
        request_id = require_request_id(request.context, context)
        if not request.channel_ids:
            abort_invalid(context, request_id, "at least one channel_id is required")
        if any(not channel_id.strip() for channel_id in request.channel_ids):
            abort_invalid(context, request_id, "channel_ids must not contain empty values")
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)

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
    def __init__(self, auth: AuthApplication) -> None:
        self._auth = auth

    def Heartbeat(
        self, request: presence_pb2.HeartbeatRequest, context: grpc.ServicerContext
    ) -> presence_pb2.PresenceResponse:
        request_id = require_request_id(request.context, context)
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "PresenceService.Heartbeat")

    def GetPresence(
        self, request: presence_pb2.GetPresenceRequest, context: grpc.ServicerContext
    ) -> presence_pb2.PresenceResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "PresenceService.GetPresence")

    def SubscribePresence(
        self,
        request: presence_pb2.SubscribePresenceRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[presence_pb2.PresenceEvent]:
        request_id = require_request_id(request.context, context)
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "PresenceService.SubscribePresence")
        yield  # pragma: no cover - keeps this method a streaming generator


class FileService(file_pb2_grpc.FileServiceServicer):
    def __init__(self, auth: AuthApplication) -> None:
        self._auth = auth

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
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "FileService.UploadFile")

    def DownloadFile(
        self, request: file_pb2.DownloadFileRequest, context: grpc.ServicerContext
    ) -> Iterator[file_pb2.DownloadFileResponse]:
        request_id = require_request_id(request.context, context)
        require_text(request.file_id, "file_id", request_id, context)
        try:
            self._auth.authenticate(get_auth_token(), request_id=request_id)
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        abort_unimplemented(context, request_id, "FileService.DownloadFile")
        yield  # pragma: no cover - keeps this method a streaming generator


class AdminService(admin_pb2_grpc.AdminServiceServicer):
    def __init__(self, application: AdminApplication) -> None:
        self._application = application

    def CreateUser(
        self, request: admin_pb2.CreateUserRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.username, "username", request_id, context)
        require_text(request.password, "password", request_id, context)
        require_text(request.role, "role", request_id, context)
        try:
            user = self._application.create_user(
                get_auth_token(),
                request.username,
                request.password,
                request.role,
                request_id=request_id,
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return admin_pb2.UserResponse(
            status=_ok_status(request_id, "user created"), user=_user_summary(user)
        )

    def SetUserStatus(
        self, request: admin_pb2.SetUserStatusRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        require_text(request.status, "status", request_id, context)
        try:
            user = self._application.set_user_status(
                get_auth_token(),
                request.user_id,
                request.status,
                request_id=request_id,
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return admin_pb2.UserResponse(
            status=_ok_status(request_id, "user status updated"),
            user=_user_summary(user),
        )

    def SetUserRole(
        self, request: admin_pb2.SetUserRoleRequest, context: grpc.ServicerContext
    ) -> admin_pb2.UserResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.user_id, "user_id", request_id, context)
        require_text(request.role, "role", request_id, context)
        try:
            user = self._application.set_user_role(
                get_auth_token(),
                request.user_id,
                request.role,
                request_id=request_id,
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return admin_pb2.UserResponse(
            status=_ok_status(request_id, "user role updated"),
            user=_user_summary(user),
        )

    def ArchiveChannel(
        self, request: admin_pb2.ArchiveChannelRequest, context: grpc.ServicerContext
    ) -> channel_pb2.ChannelResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        try:
            channel = self._application.archive_channel(
                get_auth_token(), request.channel_id, request_id=request_id
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return channel_pb2.ChannelResponse(
            status=_ok_status(request_id, "channel archived"),
            channel=_channel_summary(channel),
        )

    def ManageChannelMember(
        self,
        request: admin_pb2.ManageChannelMemberRequest,
        context: grpc.ServicerContext,
    ) -> common_pb2.EmptyResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        require_text(request.user_id, "user_id", request_id, context)
        try:
            self._application.manage_member(
                get_auth_token(),
                request.channel_id,
                request.user_id,
                request.add,
                request_id=request_id,
            )
        except ApplicationError as error:
            abort_application_error(context, error, request_id)
        return common_pb2.EmptyResponse(
            status=_ok_status(request_id, "channel membership updated")
        )
