"""Shared gRPC metadata interceptors for correlation and authentication data."""

from __future__ import annotations

from collections import namedtuple
from contextvars import ContextVar, Token
from logging import LoggerAdapter
from typing import Any, Callable, Iterable, Iterator

import grpc

from common.metadata import new_request_id


REQUEST_ID_HEADER = "x-request-id"
AUTHORIZATION_HEADER = "authorization"

_request_id: ContextVar[str] = ContextVar("grpc_request_id", default="")
_auth_token: ContextVar[str | None] = ContextVar("grpc_auth_token", default=None)


def get_request_id() -> str:
    """Return the request ID extracted for the current RPC."""

    return _request_id.get()


def get_auth_token() -> str | None:
    """Return the bearer token extracted for the current RPC, if present."""

    return _auth_token.get()


def _metadata_dict(metadata: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {key.lower(): value for key, value in metadata}


def _extract_bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _set_context(request_id: str, auth_token: str | None) -> tuple[Token[str], Token[str | None]]:
    return _request_id.set(request_id), _auth_token.set(auth_token)


def _reset_context(tokens: tuple[Token[str], Token[str | None]]) -> None:
    request_token, auth_token = tokens
    _request_id.reset(request_token)
    _auth_token.reset(auth_token)


class RequestMetadataInterceptor(grpc.ServerInterceptor):
    """Extract request ID and bearer-token metadata around every RPC shape."""

    def __init__(self, logger: LoggerAdapter | None = None) -> None:
        self._logger = logger

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler | None],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = continuation(handler_call_details)
        if handler is None:
            return None

        metadata = _metadata_dict(handler_call_details.invocation_metadata or ())
        request_id = metadata.get(REQUEST_ID_HEADER, "").strip() or new_request_id()
        auth_token = _extract_bearer_token(metadata.get(AUTHORIZATION_HEADER))
        if self._logger is not None:
            self._logger.info(
                "rpc_received",
                extra={
                    "request_id": request_id,
                    "rpc_method": handler_call_details.method,
                    "auth_token_present": auth_token is not None,
                },
            )

        def unary_unary(request: Any, context: grpc.ServicerContext) -> Any:
            tokens = _set_context(request_id, auth_token)
            try:
                return handler.unary_unary(request, context)
            finally:
                _reset_context(tokens)

        def unary_stream(request: Any, context: grpc.ServicerContext) -> Iterator[Any]:
            tokens = _set_context(request_id, auth_token)
            try:
                yield from handler.unary_stream(request, context)
            finally:
                _reset_context(tokens)

        def stream_unary(requests: Iterator[Any], context: grpc.ServicerContext) -> Any:
            tokens = _set_context(request_id, auth_token)
            try:
                return handler.stream_unary(requests, context)
            finally:
                _reset_context(tokens)

        def stream_stream(
            requests: Iterator[Any], context: grpc.ServicerContext
        ) -> Iterator[Any]:
            tokens = _set_context(request_id, auth_token)
            try:
                yield from handler.stream_stream(requests, context)
            finally:
                _reset_context(tokens)

        if handler.request_streaming and handler.response_streaming:
            return grpc.stream_stream_rpc_method_handler(
                stream_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        if handler.request_streaming:
            return grpc.stream_unary_rpc_method_handler(
                stream_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        if handler.response_streaming:
            return grpc.unary_stream_rpc_method_handler(
                unary_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )
        return grpc.unary_unary_rpc_method_handler(
            unary_unary,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


_ClientCallDetailsBase = namedtuple(
    "_ClientCallDetailsBase",
    ("method", "timeout", "metadata", "credentials", "wait_for_ready", "compression"),
)


class _ClientCallDetails(_ClientCallDetailsBase, grpc.ClientCallDetails):
    pass


class MetadataClientInterceptor(
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
):
    """Add a request ID and optional bearer token to outgoing calls."""

    def __init__(self, *, request_id: str | None = None, token: str | None = None) -> None:
        self._request_id = request_id
        self._token = token

    def _details(self, details: grpc.ClientCallDetails) -> grpc.ClientCallDetails:
        metadata = [
            (key, value)
            for key, value in (details.metadata or ())
            if key.lower() not in {REQUEST_ID_HEADER, AUTHORIZATION_HEADER}
        ]
        metadata.append((REQUEST_ID_HEADER, self._request_id or new_request_id()))
        if self._token:
            metadata.append((AUTHORIZATION_HEADER, f"Bearer {self._token}"))
        return _ClientCallDetails(
            details.method,
            details.timeout,
            tuple(metadata),
            details.credentials,
            details.wait_for_ready,
            details.compression,
        )

    def intercept_unary_unary(self, continuation: Any, details: Any, request: Any) -> Any:
        return continuation(self._details(details), request)

    def intercept_unary_stream(self, continuation: Any, details: Any, request: Any) -> Any:
        return continuation(self._details(details), request)

    def intercept_stream_unary(self, continuation: Any, details: Any, requests: Any) -> Any:
        return continuation(self._details(details), requests)

    def intercept_stream_stream(self, continuation: Any, details: Any, requests: Any) -> Any:
        return continuation(self._details(details), requests)
