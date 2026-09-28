"""Construction of the independent Phase 4 LLM gRPC server."""

from __future__ import annotations

from concurrent import futures
from logging import LoggerAdapter

import grpc

from common.config import Settings
from common.grpc_metadata import RequestMetadataInterceptor
from llm_server.adapters import DeterministicMockAdapter, LlamaCppAdapter, ModelAdapter
from llm_server.services import LLMService
from proto.chat.v1 import health_pb2_grpc, llm_pb2_grpc
from server.services import HealthService


def create_llm_server(
    settings: Settings,
    *,
    bind_address: str | None = None,
    logger: LoggerAdapter | None = None,
    adapter: ModelAdapter | None = None,
) -> tuple[grpc.Server, str]:
    """Create and register the independent inference service."""

    if adapter is None:
        adapter = (
            DeterministicMockAdapter()
            if settings.llm_adapter == "mock"
            else LlamaCppAdapter(
                settings.llm_model_path,
                context_window=settings.llm_context_window,
                max_output_tokens=settings.llm_max_output_tokens,
                threads=settings.llm_threads,
                gpu_layers=settings.llm_gpu_layers,
                temperature=settings.llm_temperature,
            )
        )

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_workers),
        interceptors=(RequestMetadataInterceptor(logger),),
    )
    health_pb2_grpc.add_HealthServiceServicer_to_server(
        HealthService(service_name="llm-server", node_id=settings.llm_node_id), server
    )
    llm_pb2_grpc.add_LLMServiceServicer_to_server(
        LLMService(
            adapter,
            max_context_messages=settings.llm_max_context_messages,
            max_context_chars=settings.llm_max_context_chars,
        ),
        server,
    )

    requested_address = bind_address or settings.llm_endpoint.address
    bound_port = server.add_insecure_port(requested_address)
    if bound_port == 0:
        raise RuntimeError(f"gRPC could not bind LLM server to {requested_address}")
    host = requested_address.rsplit(":", maxsplit=1)[0]
    return server, f"{host}:{bound_port}"
