"""Construction of the independent Phase 1 LLM gRPC server."""

from __future__ import annotations

from concurrent import futures
from logging import LoggerAdapter

import grpc

from common.config import Settings
from common.grpc_metadata import RequestMetadataInterceptor
from llm_server.services import LLMService
from proto.chat.v1 import health_pb2_grpc, llm_pb2_grpc
from server.services import HealthService


def create_llm_server(
    settings: Settings,
    *,
    bind_address: str | None = None,
    logger: LoggerAdapter | None = None,
) -> tuple[grpc.Server, str]:
    """Create and register the independent LLM service skeleton."""

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_workers),
        interceptors=(RequestMetadataInterceptor(logger),),
    )
    health_pb2_grpc.add_HealthServiceServicer_to_server(
        HealthService(service_name="llm-server", node_id=settings.llm_node_id), server
    )
    llm_pb2_grpc.add_LLMServiceServicer_to_server(LLMService(), server)

    requested_address = bind_address or settings.llm_endpoint.address
    bound_port = server.add_insecure_port(requested_address)
    if bound_port == 0:
        raise RuntimeError(f"gRPC could not bind LLM server to {requested_address}")
    host = requested_address.rsplit(":", maxsplit=1)[0]
    return server, f"{host}:{bound_port}"
