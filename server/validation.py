"""Transport-level validation shared by Phase 1 gRPC skeletons."""

from __future__ import annotations

from typing import NoReturn

import grpc


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
        f"{operation} is defined but not implemented in Phase 1",
    )
