"""Construction of the Phase 3 chat gRPC server."""

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
from server.application.admin import AdminApplication
from server.application.auth import AuthApplication
from server.application.channels import ChannelApplication
from server.application.chat import ChatApplication
from server.application.files import FileApplication
from server.application.presence import PresenceApplication
from server.database import Database, apply_migrations
from server.events import EventBroker
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


def create_chat_server(
    settings: Settings,
    *,
    bind_address: str | None = None,
    logger: LoggerAdapter | None = None,
) -> tuple[grpc.Server, str]:
    """Create and register the Phase 3 chat-side services."""

    database = Database(settings.chat_database_path)
    apply_migrations(database)
    unit_of_work_factory = SQLiteUnitOfWorkFactory(database)
    auth_application = AuthApplication(
        unit_of_work_factory,
        session_ttl_seconds=settings.session_ttl_seconds,
    )
    channel_application = ChannelApplication(unit_of_work_factory, auth_application)
    admin_application = AdminApplication(unit_of_work_factory, auth_application)
    events = EventBroker()
    chat_application = ChatApplication(
        unit_of_work_factory,
        auth_application,
        events,
        max_message_length=settings.max_message_length,
    )
    presence_application = PresenceApplication(
        auth_application,
        events,
        timeout_seconds=settings.presence_timeout_seconds,
    )
    file_application = FileApplication(
        unit_of_work_factory,
        auth_application,
        storage_path=settings.file_storage_path,
        max_size_bytes=settings.max_file_size_bytes,
        allowed_content_types=settings.allowed_file_types,
    )

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_workers),
        interceptors=(RequestMetadataInterceptor(logger),),
    )
    health_pb2_grpc.add_HealthServiceServicer_to_server(
        HealthService(service_name="chat-server", node_id=settings.chat_node_id), server
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(
        AuthService(auth_application), server
    )
    channel_pb2_grpc.add_ChannelServiceServicer_to_server(
        ChannelService(channel_application), server
    )
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatService(
            chat_application,
            events,
            keepalive_seconds=settings.stream_keepalive_seconds,
        ),
        server,
    )
    presence_pb2_grpc.add_PresenceServiceServicer_to_server(
        PresenceService(presence_application, events), server
    )
    file_pb2_grpc.add_FileServiceServicer_to_server(
        FileService(file_application, chunk_size=settings.file_chunk_size_bytes), server
    )
    admin_pb2_grpc.add_AdminServiceServicer_to_server(
        AdminService(admin_application), server
    )

    requested_address = bind_address or settings.chat_endpoint.address
    bound_port = server.add_insecure_port(requested_address)
    if bound_port == 0:
        raise RuntimeError(f"gRPC could not bind chat server to {requested_address}")
    host = requested_address.rsplit(":", maxsplit=1)[0]
    return server, f"{host}:{bound_port}"
