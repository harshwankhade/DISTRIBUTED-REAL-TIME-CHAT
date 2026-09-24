# Distributed Real-time Chat and Collaboration Tool

This Python project is built one approved phase at a time for a distributed
systems course. Phase 1 provides stable Protocol Buffer contracts and runnable
gRPC transport skeletons. It does **not** provide chat business behavior yet.

## Current status

- Completed: Phase 0 - requirements and repository scaffold
- Completed: Phase 1 - protobuf contracts and gRPC skeleton
- Next, only when explicitly requested: Phase 2 - users, sessions, channels,
  administration, SQLite schema, and repositories
- Not implemented: real authentication, persistent channels/messages/files,
  presence state, LLM inference, Raft, replication, or fault tolerance

## Requirements and setup

- Python 3.11 or newer
- Windows command shell for convenience scripts

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\scripts\generate_stubs.cmd
```

The generated bindings are checked into `proto/chat/v1` so a fresh evaluator
can run the system immediately after installing requirements. Regenerate them
whenever a `.proto` source changes.

## Repository layout

```text
.
|-- client/                 # Identity command and gRPC smoke client
|-- common/                 # Configuration, JSON logs, IDs, interceptors
|-- docs/                   # Requirements, architecture, API and phase reports
|-- domain/                 # Initial data-only domain models
|-- llm_server/             # Independent LLM gRPC skeleton
|-- proto/chat/v1/          # Versioned .proto sources and generated bindings
|-- scripts/                # Stub generation and process launchers
|-- server/                 # Chat-side gRPC skeletons and repository ports
|-- tests/                  # Unit, contract and gRPC integration tests
|-- .env.example            # Environment-variable reference
`-- requirements.txt        # Reproducible Phase 1 dependencies
```

There is intentionally no `raft/` directory before Phase 5.

## Version 1 gRPC surface

| Service | Phase 1 RPCs |
|---|---|
| `HealthService` | `Check` |
| `AuthService` | `Login`, `Logout` |
| `ChannelService` | create, list, join, leave |
| `ChatService` | send, history, server-streamed events |
| `PresenceService` | heartbeat, lookup, server-streamed events |
| `FileService` | client-streamed upload, server-streamed download |
| `AdminService` | user status/role and channel/member management |
| `LLMService` | smart reply, summary, suggestion |

Only health checks and chat-stream keepalives succeed in Phase 1. Valid calls
to feature RPCs return gRPC `UNIMPLEMENTED`; malformed requests return a defined
status such as `INVALID_ARGUMENT`.

## Configuration

Settings come from environment variables and are listed in `.env.example`.
Important Phase 1 values include `CHAT_HOST`, `CHAT_PORT`, `LLM_HOST`,
`LLM_PORT`, `GRPC_WORKERS`, `RPC_TIMEOUT_SECONDS`,
`STREAM_KEEPALIVE_SECONDS`, and `SHUTDOWN_GRACE_SECONDS`.

`.env.example` is a reference, not an automatically loaded file. Example:

```powershell
$env:CHAT_PORT = "51051"
$env:LOG_LEVEL = "DEBUG"
```

## Run and smoke-test the services

Start the chat skeleton in terminal 1:

```powershell
.\scripts\start_chat.cmd
```

Start the independent LLM skeleton in terminal 2:

```powershell
.\scripts\start_llm.cmd
```

Run the acceptance smoke client in terminal 3:

```powershell
.\scripts\start_client.cmd --smoke
```

The smoke client checks that chat health is serving, a valid login skeleton
returns `UNIMPLEMENTED`, the event subscription receives a transport keepalive,
and stream cancellation succeeds. Stop servers with `Ctrl+C`.

One-shot startup checks are also available:

```powershell
.\scripts\start_chat.cmd --once
.\scripts\start_llm.cmd --once
.\scripts\start_client.cmd --once
```

## Run tests

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
```

## Metadata and deadlines

- Clients send `x-request-id` metadata; the shared client interceptor can create
  it and the server interceptor extracts it for logging and handlers.
- Optional bearer tokens use `authorization: Bearer <token>`. Phase 1 extracts
  but does not validate tokens.
- Request messages also contain a `RequestContext`; state-changing contracts
  reserve `client_request_id` for later idempotency.
- Clients apply explicit RPC deadlines. Services preserve request IDs in status
  messages or trailing metadata.

See [API contracts](docs/api_contracts.md),
[architecture](docs/architecture.md), and the
[Phase 1 report](docs/phases/phase_1_report.md) for details.

## Phase 1 limitations

No credentials are checked, no token is issued, and nothing is persisted.
Streaming keepalives only verify transport and cancellation. File bytes are not
accepted, LLM answers are not generated, and there is no Raft behavior.

