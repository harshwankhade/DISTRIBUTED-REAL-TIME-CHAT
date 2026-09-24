"""Construction of the Phase 1 chat gRPC server."""

from __future__ import annotations

from concurrent import futures
from logging import LoggerAdapter

import grpc

from common.config import Settings
from common.grpc_metadata import RequestMetadataInterceptor
from proto.chat.v1 import (
    admin_pb2_grpc,
    auth_pb2_grpc,
    channel_pb2_grpc,
    chat_pb2_grpc,
    file_pb2_grpc,
    health_pb2_grpc,
    presence_pb2_grpc,
)
from server.services import (
    AdminService,
    AuthService,
    ChannelService,
    ChatService,
    FileService,
    HealthService,
    PresenceService,
)


def create_chat_server(
    settings: Settings,
    *,
    bind_address: str | None = None,
    logger: LoggerAdapter | None = None,
) -> tuple[grpc.Server, str]:
    """Create and register the chat-side Phase 1 service skeletons."""

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_workers),
        interceptors=(RequestMetadataInterceptor(logger),),
    )
    health_pb2_grpc.add_HealthServiceServicer_to_server(
        HealthService(service_name="chat-server", node_id=settings.chat_node_id), server
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(AuthService(), server)
    channel_pb2_grpc.add_ChannelServiceServicer_to_server(ChannelService(), server)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatService(keepalive_seconds=settings.stream_keepalive_seconds), server
    )
    presence_pb2_grpc.add_PresenceServiceServicer_to_server(PresenceService(), server)
    file_pb2_grpc.add_FileServiceServicer_to_server(FileService(), server)
    admin_pb2_grpc.add_AdminServiceServicer_to_server(AdminService(), server)

    requested_address = bind_address or settings.chat_endpoint.address
    bound_port = server.add_insecure_port(requested_address)
    if bound_port == 0:
        raise RuntimeError(f"gRPC could not bind chat server to {requested_address}")
    host = requested_address.rsplit(":", maxsplit=1)[0]
    return server, f"{host}:{bound_port}"
