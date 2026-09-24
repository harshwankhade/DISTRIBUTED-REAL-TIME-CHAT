# Phase 1 - Protobuf Contracts and gRPC Skeleton

**Status:** Complete

## Scope completed

Phase 1 added versioned Protocol Buffer contracts for health, authentication,
channels, chat, presence, files, administration, and LLM assistance. It generated
Python bindings, connected typed service skeletons to independent chat and LLM
gRPC servers, added shared metadata interceptors, and provided an executable
smoke-test client.

No Phase 2 business or persistence behavior was implemented.

## Assumptions

- The prompt heading saying "phase 2" was a typo because all supplied objectives
  and the explicit implementation prompt requested Phase 1.
- Python 3.11+ remains supported; verification used Python 3.14.6.
- Phase 1 uses insecure gRPC on local/private development addresses. Transport
  security and deployment certificates are not part of this phase.
- Tokens travel in `authorization` metadata. Request messages do not contain
  token fields.
- Checked-in generated files make clean evaluation easier, while the generation
  command remains reproducible.

## What was implemented

- Nine v1 `.proto` contract files and their generated Python/gRPC modules.
- Health checks on both chat and independent LLM servers.
- Typed skeletons for every required service.
- Explicit `INVALID_ARGUMENT` validation and `UNIMPLEMENTED` feature responses.
- Server and client interceptors for request IDs and optional bearer tokens.
- Request-level JSON logs without exposing token values.
- A real server-streaming subscription with typed transport keepalives and
  cancellation handling.
- Streaming upload/download contract shapes for future chunked file transfer.
- A smoke client covering health, login skeleton, streaming, and cancellation.
- Contract, metadata, validation, streaming, independent-LLM, and startup tests.

## Distributed-systems concepts involved

### Interface contracts

Protocol Buffers define language-neutral, versioned messages and RPC methods.
They separate callers from service implementation details. v1 field numbers and
meanings should remain stable so later server changes do not rewrite clients.

### Correlation and deadlines

Request IDs travel in metadata and request envelopes so one logical operation
can be traced across future service calls. Clients set deadlines because remote
calls may hang or fail. This phase verifies deadline-capable calls but does not
implement retries.

### Streaming and cancellation

`SubscribeEvents` keeps one server-streaming RPC open and notices client
cancellation. Keepalives prove the transport is active; they do not provide
message ordering, replay, persistence, or delivery guarantees.

### Service isolation

The LLM endpoint runs on a separate gRPC server. It cannot access persistence or
mutate chat state in this phase. Raft, replication, leaders, and consensus are
not implemented or simulated.

## Architecture and design decisions

- Contracts live in `proto/chat/v1` and use `distributed_chat.v1`.
- Generated modules live beside source contracts to preserve normal Python
  imports and make regeneration simple.
- Tokens use standard bearer metadata and are only extracted, never validated
  or logged. Validation belongs to Phase 2.
- Request messages use `RequestContext`; retryable writes reserve a distinct
  `client_request_id` for later idempotency.
- Chat keepalives are the only successful streaming payload in Phase 1. Other
  feature RPCs fail explicitly instead of returning fake data.
- File upload is client streaming and download is server streaming to avoid a
  future whole-file-in-memory design.
- Worker count, addresses, deadlines, keepalive interval, and shutdown grace are
  configuration values rather than business-logic constants.

## Files created or modified

Every file changed in Phase 1 is listed below. Generated files are marked.

```text
.env.example
.gitignore
README.md
requirements.txt

client/grpc_client.py
client/main.py

common/config.py
common/grpc_metadata.py
common/runtime.py

docs/api_contracts.md
docs/architecture.md
docs/requirements.md
docs/phases/phase_1_report.md

llm_server/grpc_server.py
llm_server/main.py
llm_server/services.py

proto/__init__.py
proto/chat/__init__.py
proto/chat/v1/__init__.py
proto/chat/v1/admin.proto
proto/chat/v1/auth.proto
proto/chat/v1/channel.proto
proto/chat/v1/chat.proto
proto/chat/v1/common.proto
proto/chat/v1/file.proto
proto/chat/v1/health.proto
proto/chat/v1/llm.proto
proto/chat/v1/presence.proto
proto/chat/v1/admin_pb2.py                 (generated)
proto/chat/v1/admin_pb2_grpc.py            (generated)
proto/chat/v1/auth_pb2.py                  (generated)
proto/chat/v1/auth_pb2_grpc.py             (generated)
proto/chat/v1/channel_pb2.py               (generated)
proto/chat/v1/channel_pb2_grpc.py          (generated)
proto/chat/v1/chat_pb2.py                  (generated)
proto/chat/v1/chat_pb2_grpc.py             (generated)
proto/chat/v1/common_pb2.py                (generated)
proto/chat/v1/common_pb2_grpc.py           (generated)
proto/chat/v1/file_pb2.py                  (generated)
proto/chat/v1/file_pb2_grpc.py             (generated)
proto/chat/v1/health_pb2.py                (generated)
proto/chat/v1/health_pb2_grpc.py           (generated)
proto/chat/v1/llm_pb2.py                   (generated)
proto/chat/v1/llm_pb2_grpc.py              (generated)
proto/chat/v1/presence_pb2.py              (generated)
proto/chat/v1/presence_pb2_grpc.py         (generated)

scripts/generate_stubs.cmd
scripts/generate_stubs.py
scripts/start_chat.cmd
scripts/start_client.cmd
scripts/start_llm.cmd

server/grpc_server.py
server/main.py
server/services.py
server/validation.py

tests/test_grpc_skeleton.py
tests/test_placeholders.py
tests/test_proto_contracts.py
```

Phase 0 model, repository, error, metadata-helper, and logging files remain in
place. The start scripts were updated to prefer the local virtual environment.

## How the code works

The generation script compiles every v1 source into Python message and service
classes. Each server registers the generated service base classes with typed
implementations. The metadata interceptor wraps unary and streaming handlers,
placing request ID and token information in context-local variables.

Health methods return serving state. Valid feature calls reach a typed method
and return `UNIMPLEMENTED`. Invalid required fields return `INVALID_ARGUMENT`.
The chat subscription emits keepalives until the client cancels or its deadline
expires. The smoke client performs these calls with explicit timeouts.

## Configuration and external prerequisites

Phase 1 requires the three pinned packages in `requirements.txt`:

- `grpcio==1.84.0`
- `grpcio-tools==1.84.0`
- `protobuf==7.36.2`

They were installed into `.venv`. Internet access is needed only for a fresh
dependency installation. No account, API key, model download, firewall change,
or external database is needed.

## Expected output and behavior

The chat and LLM servers log `phase: 1`, their node identity, and their bound
address. The smoke client should log:

- `health_serving: true`
- `login_status: UNIMPLEMENTED`
- `stream_event_type: CHAT_EVENT_TYPE_KEEPALIVE`
- `stream_cancelled: true`

Malformed login input should return gRPC `INVALID_ARGUMENT` rather than an
application response or unhandled exception.

## Tests performed

The following checks were run successfully on September 24, 2026:

```powershell
.venv\Scripts\python scripts\generate_stubs.py
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.\scripts\start_chat.cmd --once
.\scripts\start_llm.cmd --once
```

Stub generation compiled all 9 protocol files. Compilation returned exit code
0. All 16 automated tests passed. Tests include the 7 retained Phase 0 checks,
contract shape checks, metadata/request-ID behavior, invalid input,
`UNIMPLEMENTED`, chat-stream cancellation, the smoke-client path, and the
separate LLM server.

A manual process-level smoke test also ran a hidden chat-server process on
`127.0.0.1:55051`, invoked `python -m client --smoke`, and then stopped the
server. All four expected smoke fields reported success.

## Exact verification steps for the user

In the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\scripts\generate_stubs.cmd
.venv\Scripts\python -m unittest discover -s tests -v
```

Then open three terminals:

```powershell
.\scripts\start_chat.cmd
```

```powershell
.\scripts\start_llm.cmd
```

```powershell
.\scripts\start_client.cmd --smoke
```

Confirm the smoke log contains the four expected values above. Stop both
servers with `Ctrl+C`.

## Known limitations, placeholders, mocks, and TODOs

- Feature services are transport skeletons and intentionally return
  `UNIMPLEMENTED` after basic validation.
- Bearer tokens are extracted but not authenticated or authorized.
- Request-ID metadata and envelope IDs are not yet rejected when they differ.
- The chat stream contains transport keepalives only.
- File streams transfer no bytes and perform no checksum/security checks.
- The LLM server loads no model and returns no answer.
- Local gRPC channels are insecure; deployment TLS is not configured.
- There is no retry policy or idempotency store.

## Explicitly out-of-scope functionality not implemented

User creation, password hashing, sessions, token issuance/expiry, channel
persistence, authorization, administration behavior, messages/history,
presence state, file storage, checksums, LLM inference/context filtering,
SQLite schema/migrations, retries, duplicate suppression, Raft, leader election,
replication, majority commit, failover, and recovery are not implemented.
