# Phase 4 - Separate LLM Service and Milestone 1 Demo

## Status

Complete. Phase 4 adds a separate, usable local-LLM process, authenticated AI
features on the chat server, and a lightweight Tkinter demo client. All 45
automated tests pass, and the real Qwen GGUF was loaded for a manual inference
smoke check. No Raft functionality was added.

## Scope completed

- Smart replies based on recent authorized channel messages.
- Summaries restricted to a selected channel and UTC time range.
- Context-aware next-step suggestions.
- A separate gRPC LLM process with a deterministic mock and a local Qwen
  `llama-cpp-python` adapter.
- Server-built, membership-checked, size-bounded context.
- Downstream deadlines and graceful fallback when the LLM fails or is offline.
- Tkinter flows for the Milestone 1 collaboration features.
- Reproducible model/runtime setup and one-command demo start/stop scripts.

## Assumptions

- The accepted local model is Qwen2.5-3B-Instruct Q4_K_M under its published
  `qwen-research` license. The evaluator accepts that license before download.
- CPU-only inference is the portable default (`LLM_GPU_LAYERS=0`) for the
  target 16 GB Intel Core Ultra laptop. Intel Arc acceleration is not required.
- A 24-hour range is the GUI's convenient summary default; the RPC accepts an
  explicit range.
- AI output is advisory and is not durable unless a user sends it as a normal
  message.

## What was implemented

The chat server now exposes the existing v1 `LLMService` as an authenticated
gateway. It derives identity from the bearer token, verifies channel membership,
loads messages from SQLite, applies time/message/character limits, and sends
only that subset to Node 1. Caller-provided `requester_id` and
`authorized_context` are ignored at this boundary.

Node 1 validates the downstream request and delegates generation to a model
adapter. `DeterministicMockAdapter` produces stable test output.
`LlamaCppAdapter` lazily imports `llama-cpp-python`, loads the local Qwen GGUF,
serializes native inference for thread safety, and uses domain-specific prompts
that forbid invented or out-of-context facts.

The Tkinter client supports login/logout, channel list/create/join/leave,
history, live message streams, sending, heartbeats, uploads/downloads with
checksum verification, the three AI operations, and basic admin user creation.

## Distributed-systems concepts involved

**Service separation:** the LLM and chat application are separate OS processes
and communicate only through gRPC. Node 1 can fail independently.

**Least-privilege data flow:** authentication and authorization stay with the
chat server that owns users, membership, and messages. The inference service
has no database access and receives only a bounded projection of authorized
data.

**Partial failure and deadlines:** an LLM connection failure, inference error,
or deadline expiry is contained. The gateway returns a clearly labelled
fallback, while unrelated chat operations continue.

**Bounded resources:** message count, character count, model context window,
output tokens, and RPC duration are configured limits. This reduces latency and
prevents an unbounded channel history from becoming one request.

These are service-boundary and fault-isolation properties. They are not
consensus, replication, reliable delivery across servers, or Raft guarantees.

## Architecture and design decisions

- The existing `LLMService` protobuf remains unchanged. Clients call that
  service on the chat address; the gateway calls the same typed service on the
  configured LLM address. This preserves the stabilized Phase 1 contract.
- Authorization is performed before the network hop. Letting Node 1 query the
  chat database would duplicate security rules and increase its privileges.
- The test mock is injected through the same adapter boundary as the real
  model, so integration tests exercise real gRPC separation without slow or
  nondeterministic inference.
- A failed AI request returns status code `OK` with an explicit
  `local LLM unavailable; graceful fallback returned` message and safe fallback
  text. This preserves the v1 response enum while making degradation visible.
- Qwen output is generated with a locked adapter because one model instance is
  shared by gRPC worker threads. Multiple RPCs may arrive concurrently, but the
  native model invocation is serialized for predictable local resource use.
- No database migration was needed: context is a read-only view of existing
  durable messages, and generated text is not persisted automatically.

## Files created or modified

Created:

- `requirements-llm.txt` - pinned optional local-inference runtime and CPU wheel source.
- `llm_server/adapters.py` - adapter interface, deterministic mock, and Qwen llama.cpp adapter.
- `server/llm_client.py` - deadline-bound typed client from chat to Node 1.
- `server/application/assistant.py` - authorization, context construction, orchestration, and fallbacks.
- `client/api.py` - typed client operations used by the GUI.
- `client/gui.py` - Tkinter Milestone 1 interface.
- `tests/test_phase4_llm.py` - privacy, bounds, deadline, offline, and availability integration tests.
- `scripts/install_llm_runtime.cmd` and `scripts/download_model.cmd` - reproducible local-model setup.
- `scripts/start_milestone1.cmd`, `scripts/start_milestone1.ps1`,
  `scripts/stop_milestone1.cmd`, and `scripts/stop_milestone1.ps1` - demo lifecycle.
- `docs/phases/phase_4_report.md` - this report.

Modified:

- `.gitignore` - ignores local model and demo logs.
- `.env.example` - documents all Phase 4 settings without secrets.
- `common/config.py` - validates model, context, thread, temperature, and timeout settings.
- `llm_server/services.py`, `llm_server/grpc_server.py`, and `llm_server/main.py` - real inference service wiring and identity.
- `server/repositories/sqlite.py` - bounded channel/time-range context query.
- `server/services.py`, `server/grpc_server.py`, `server/main.py`, and
  `server/application/__init__.py` - authenticated gateway registration and Phase 4 identity.
- `client/main.py` - `--gui` launch mode while preserving `--smoke`.
- `tests/test_config.py`, `tests/test_grpc_skeleton.py`, and
  `tests/test_placeholders.py` - Phase 4 expectations and configuration coverage.
- `README.md`, `docs/architecture.md`, and `docs/api_contracts.md` - fresh setup,
  trust boundary, launch, demo, and limitations.

The user's local `.env` was updated to choose the local adapter and local model
path. It remains ignored and is not a distributable configuration example.
Generated protobuf files were not changed because the Phase 1 v1 contract was
already sufficient.

## How the code works

An authenticated GUI request reaches the chat server's AI gateway. The gateway
authenticates the token, checks membership, queries the newest allowed messages
within the optional range, trims the context, and calls Node 1 with a deadline.
Node 1 converts those messages into a task-specific prompt and invokes either
the injected mock or the local GGUF model. The response returns over gRPC. Any
downstream `RpcError` becomes a safe fallback, not a chat-server failure.

## Configuration and external prerequisites

The user accepted the Qwen license and model download before implementation.
The model file is stored at
`models/qwen2.5-3b-instruct-q4_k_m.gguf` and is not committed. Install the base
dependencies, run `scripts\install_llm_runtime.cmd`, and then
`scripts\download_model.cmd`. Set `LLM_ADAPTER=local` for Qwen or `mock` for a
fast deterministic demo. No API key is needed.

## Expected output and behavior

The LLM service logs its Node 1 identity and configured adapter. The chat server
logs its separate identity. A member receives an AI answer based only on their
selected channel. A non-member receives `PERMISSION_DENIED`. If Node 1 is
stopped or too slow, the user receives a labelled fallback and can still send,
stream, retrieve, upload, and download through the chat server.

## Tests performed

Latest automated result: **45 tests passed**; `compileall` and `pip check` also
passed. Coverage includes all earlier
Phase 0-3 behavior plus forged-context rejection, channel privacy, non-member
denial, summary ranges, context limits, deterministic model calls, deadline
fallback, offline fallback, and successful messaging during an LLM outage.

A real-adapter smoke check loaded the downloaded 2,104,932,768-byte Qwen GGUF on
CPU and generated a grounded reply. This check used 8 threads, zero GPU layers,
and no external API.

## Exact verification steps

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m unittest tests.test_phase4_llm -v
.venv\Scripts\python -m pip check
```

For a manual end-to-end demonstration:

```powershell
.\scripts\start_milestone1.cmd
.\scripts\start_client.cmd --gui
.\scripts\stop_milestone1.cmd
```

## Known limitations, placeholders, mocks, and TODOs

- The deterministic mock is a test/evaluator option, not an AI model.
- The local model may be slow on CPU and has no Intel Arc acceleration enabled.
- The GUI exposes basic admin user creation; the complete admin surface remains
  available through tested gRPC RPCs rather than dedicated GUI forms.
- Presence is heartbeat-based and process-local; the GUI sends a heartbeat
  every five seconds but does not yet show a roster panel.
- gRPC is plaintext on localhost; TLS is a future deployment concern.
- LLM responses are not saved automatically and have no factual guarantee.

## Explicitly out of scope

Phase 4 did not add Raft, leader/follower roles, elections, replicated logs,
majority commit, cross-server message ordering, failover, node recovery,
multi-chat-server deployment, file-byte replication, or LLM participation in
durable state. Those remain Milestone 2 work and are not simulated or claimed.

## Approved post-phase usability enhancement

On 2026-09-28, the user approved an additive v1 contract extension so chat
messages show usernames rather than internal user UUIDs. `MessageView` field 7
contains `sender_username`; no existing field number or stored row changed.
New messages use the authenticated username, persisted history joins the user
record, and the Tkinter history/live-event views prefer the new field. Older
clients remain wire-compatible and fall back to `sender_id`.
