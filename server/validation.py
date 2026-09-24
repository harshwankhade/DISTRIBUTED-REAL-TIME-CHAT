"""Transport-level validation shared by Phase 1 gRPC skeletons."""

from __future__ import annotations

from typing import NoReturn

import grpc

from common.errors import ApplicationError, ErrorCode


_GRPC_STATUS_BY_ERROR = {
    ErrorCode.INVALID_ARGUMENT: grpc.StatusCode.INVALID_ARGUMENT,
    ErrorCode.UNAUTHENTICATED: grpc.StatusCode.UNAUTHENTICATED,
    ErrorCode.PERMISSION_DENIED: grpc.StatusCode.PERMISSION_DENIED,
    ErrorCode.NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    ErrorCode.ALREADY_EXISTS: grpc.StatusCode.ALREADY_EXISTS,
    ErrorCode.CONFLICT: grpc.StatusCode.FAILED_PRECONDITION,
    ErrorCode.DEADLINE_EXCEEDED: grpc.StatusCode.DEADLINE_EXCEEDED,
    ErrorCode.UNAVAILABLE: grpc.StatusCode.UNAVAILABLE,
    ErrorCode.NOT_IMPLEMENTED: grpc.StatusCode.UNIMPLEMENTED,
    ErrorCode.INTERNAL: grpc.StatusCode.INTERNAL,
}


def abort_invalid(
    context: grpc.ServicerContext, request_id: str, message: str
) -> NoReturn:
    context.set_trailing_metadata((("x-request-id", request_id),))
    context.abort(grpc.StatusCode.INVALID_ARGUMENT, message)


def require_request_id(request_context: object, context: grpc.ServicerContext) -> str:
    request_id = str(getattr(request_context, "request_id", "")).strip()
    if not request_id:
        abort_invalid(context, "", "context.request_id is required")
    return request_id


def require_text(
    value: str, field_name: str, request_id: str, context: grpc.ServicerContext
) -> None:
    if not value or not value.strip():
        abort_invalid(context, request_id, f"{field_name} is required")


def abort_unimplemented(
    context: grpc.ServicerContext, request_id: str, operation: str
) -> NoReturn:
    context.set_trailing_metadata((("x-request-id", request_id),))
    context.abort(
        grpc.StatusCode.UNIMPLEMENTED,
        f"{operation} is defined but not implemented in the current phase",
    )


def abort_application_error(
    context: grpc.ServicerContext, error: ApplicationError, fallback_request_id: str
) -> NoReturn:
    request_id = error.request_id or fallback_request_id
    context.set_trailing_metadata((("x-request-id", request_id),))
    context.abort(_GRPC_STATUS_BY_ERROR[error.code], error.message)
