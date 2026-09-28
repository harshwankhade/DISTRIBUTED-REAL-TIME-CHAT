# Version 1 gRPC Contract Guide

## Versioning and package

All Phase 1 contracts live under `proto/chat/v1` and use the protobuf package
`distributed_chat.v1`. Backward-incompatible changes should use a later version
rather than silently changing deployed v1 field meanings or field numbers.

## Shared conventions

Every request has a `RequestContext` where the RPC shape permits it:

- `request_id` correlates logs and downstream calls.
- `client_request_id` identifies retryable state-changing work and is required
  by `SendMessage` and file upload. Milestone 1 persists deduplication results for
  both operations; Phase 6 will preserve them in replicated state.

The transport also carries `x-request-id`. The client and server interceptors
manage this metadata. Authorization uses `authorization: Bearer <token>`.
The Phase 4 chat gateway validates the token before constructing AI context.

Successful response messages use `ResponseStatus`. Transport/input failures use
gRPC status codes. All Milestone 1 service contracts now have working behavior.
Request IDs are echoed in response status or trailing metadata where possible.

Clients must set deadlines. The Phase 1 smoke client uses
`RPC_TIMEOUT_SECONDS`; later operations may choose operation-specific deadlines.

`MessageView` carries both the stable `sender_id` and the display-oriented
`sender_username`. The username is an additive field (field number 7), so older
v1 clients continue to parse messages and newer clients can avoid displaying
internal UUIDs. The server remains authoritative for both values.

## Service ownership

### Chat application process

- `HealthService`: transport health and node identity.
- `AuthService`: working login and logout with expiring persisted sessions.
- `ChannelService`: working create/list/join/leave with authorization.
- `ChatService`: message send/history plus server-streamed events.
- `PresenceService`: heartbeat/status plus presence event stream.
- `FileService`: chunked client-streamed upload, server-streamed download, and
  authorized paginated channel-file listing.
- `AdminService`: working user, role/status, channel archive, and membership
  administration.
- `LLMService`: authenticated AI gateway. It rejects non-members, ignores
  untrusted caller context, queries bounded authorized history, and invokes the
  independent service with a deadline.

### Independent LLM process

- `HealthService`: independent process health.
- `LLMService`: inference-only smart reply, time-bounded summary, and contextual
  suggestion implementation. It accepts only the bounded context supplied by
  the chat application and cannot access chat persistence.

The identical v1 `LLMService` contract is intentionally exposed at two trust
boundaries: clients call it on the chat server, while the chat server calls it
on Node 1. External `requester_id` and `authorized_context` fields are ignored
by the chat gateway. Node 1 returns `UNAVAILABLE` on adapter failure; the gateway
turns downstream `RpcError` values, including deadline expiry, into an explicit
fallback response so chat remains available.

## Streaming decisions

`ChatService.SubscribeEvents` is server streaming. It verifies membership for
every requested channel, emits new-message events, provides idle keepalives,
and stays connected until cancellation or deadline. An empty channel filter is
allowed for transport smoke checks and receives keepalives but no message data.

`PresenceService.SubscribePresence` streams online/offline transitions. An
empty user filter means all users; a non-empty filter selects those user IDs.

`FileService.UploadFile` is client streaming: the first item is a metadata
header and later items are byte chunks. `DownloadFile` is server streaming: its
first response contains metadata and later responses contain byte chunks.
`ListChannelFiles` is unary and returns newest-first metadata pages using an
opaque cursor. All three operations require current channel membership.

`ChatService.SubscribeEvents` also emits `CHAT_EVENT_TYPE_FILE` with a typed
`FileMetadataView` after a new upload commits. File metadata includes the stable
uploader ID and additive `uploader_username`; file bytes never enter the event.

## Regenerating bindings

Run:

```powershell
.\scripts\generate_stubs.cmd
```

The Python generator locates the bundled protobuf include directory from
`grpc_tools`, compiles all v1 sources, and writes `*_pb2.py` and
`*_pb2_grpc.py` beside their source contracts.
