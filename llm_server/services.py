"""Typed Phase 1 LLM gRPC service skeleton."""

from __future__ import annotations

import grpc

from proto.chat.v1 import llm_pb2, llm_pb2_grpc
from server.validation import abort_unimplemented, require_request_id, require_text


class LLMService(llm_pb2_grpc.LLMServiceServicer):
    def GetSmartReply(
        self, request: llm_pb2.SmartReplyRequest, context: grpc.ServicerContext
    ) -> llm_pb2.LLMResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.requester_id, "requester_id", request_id, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "LLMService.GetSmartReply")

    def SummarizeConversation(
        self, request: llm_pb2.SummaryRequest, context: grpc.ServicerContext
    ) -> llm_pb2.LLMResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.requester_id, "requester_id", request_id, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "LLMService.SummarizeConversation")

    def GetSuggestion(
        self, request: llm_pb2.SuggestionRequest, context: grpc.ServicerContext
    ) -> llm_pb2.LLMResponse:
        request_id = require_request_id(request.context, context)
        require_text(request.requester_id, "requester_id", request_id, context)
        require_text(request.channel_id, "channel_id", request_id, context)
        abort_unimplemented(context, request_id, "LLMService.GetSuggestion")
