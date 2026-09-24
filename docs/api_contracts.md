# Version 1 gRPC Contract Guide

## Versioning and package

All Phase 1 contracts live under `proto/chat/v1` and use the protobuf package
`distributed_chat.v1`. Backward-incompatible changes should use a later version
rather than silently changing deployed v1 field meanings or field numbers.

## Shared conventions

Every request has a `RequestContext` where the RPC shape permits it:

- `request_id` correlates logs and downstream calls.
- `client_request_id` identifies retryable state-changing work and is required
  by `SendMessage`; storage-based deduplication is future Phase 3/6 work.

The transport also carries `x-request-id`. The client and server interceptors
manage this metadata. Authorization uses `authorization: Bearer <token>`.
Phase 1 extracts the token without validating it or making authorization claims.

Successful response messages use `ResponseStatus`. Transport/input failures use
gRPC status codes. Auth, channel, and admin calls now execute Phase 2 behavior.
Still-unimplemented chat, presence, file, and LLM calls return `UNIMPLEMENTED`
after applicable authentication and validation. Request IDs are echoed in
response status or trailing metadata where possible.

Clients must set deadlines. The Phase 1 smoke client uses
`RPC_TIMEOUT_SECONDS`; later operations may choose operation-specific deadlines.

## Service ownership

### Chat application process

- `HealthService`: transport health and node identity.
- `AuthService`: working login and logout with expiring persisted sessions.
- `ChannelService`: working create/list/join/leave with authorization.
- `ChatService`: message send/history plus server-streamed events.
- `PresenceService`: heartbeat/status plus presence event stream.
- `FileService`: chunked client-streamed upload and server-streamed download.
- `AdminService`: working user, role/status, channel archive, and membership
  administration.

### Independent LLM process

- `HealthService`: independent process health.
- `LLMService`: smart reply, time-bounded summary, and contextual suggestion
  contracts. Requests carry already-authorized context; Phase 4 will build and
  enforce that context.

## Streaming decisions

`ChatService.SubscribeEvents` is server streaming. Its Phase 1 implementation
emits transport keepalives and stays connected until cancellation or deadline.
It does not publish messages or presence state.

`FileService.UploadFile` is client streaming: the first item is a metadata
header and later items are byte chunks. `DownloadFile` is server streaming: its
first future response may contain metadata and later responses byte chunks.
The server validates only the upload shape before returning `UNIMPLEMENTED`.

## Regenerating bindings

Run:

```powershell
.\scripts\generate_stubs.cmd
```

The Python generator locates the bundled protobuf include directory from
`grpc_tools`, compiles all v1 sources, and writes `*_pb2.py` and
`*_pb2_grpc.py` beside their source contracts.
