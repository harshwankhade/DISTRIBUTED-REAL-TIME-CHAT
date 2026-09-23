# Phase 0 - Freeze Requirements and Scaffold the Repository

**Status:** Complete

## Scope completed

Phase 0 converted the project idea into documented user/admin permissions, data
ownership rules, process boundaries, conventions, initial domain models, a
central configuration loader, JSON logging, persistence interfaces, launch
scripts, tests, and three runnable placeholders.

No later-phase feature was implemented.

## Assumptions

- Python 3.11 or newer is available. Verification used Python 3.14.6.
- Milestone 1 uses one chat server with one local SQLite database file.
- Administrators do not automatically gain access to private channel content.
- Environment variables are sufficient for Phase 0 configuration; automatic
  `.env` file loading is not included.
- Placeholder chat and LLM processes may wait until `Ctrl+C`; `--once` exists
  for smoke testing.

## What was implemented

- Product user stories and a role/permission matrix.
- Data ownership plus request ID, timestamp, status, retry, and error rules.
- Immutable initial data models with simple validation.
- A validated environment configuration loader with safe local defaults.
- One-line structured JSON logging shared by all processes.
- Minimal repository and unit-of-work protocols for later SQLite adapters.
- Runnable chat server, independent LLM server, and client placeholders.
- Windows command launch scripts and standard-library automated tests.

## Distributed-systems concepts involved

Phase 0 establishes **service boundaries**: the client, chat application, and
LLM service are separate processes, and future remote calls will use gRPC.
It also establishes **correlation IDs** for tracing a request across services and
distinguishes them from retry/idempotency IDs.

The repository boundary and pre-generated IDs/timestamps keep future commands
compatible with deterministic Raft application. This is design preparation
only: there is no remote communication, replication, leader, consensus,
delivery guarantee, or failure recovery in Phase 0.

## Architecture and design decisions

- **SQLite per server:** requires no external service and supports transactions.
  A shared database across nodes is explicitly forbidden as fake replication.
- **Repository ports:** application code can later use SQLite and then a
  Raft-applied state machine without exposing storage choices to clients.
- **Standard library only:** avoids installing dependencies before they are
  needed. gRPC packages will be introduced with Phase 1 contracts.
- **Environment configuration:** node IDs, ports, paths, and log levels can vary
  by deployment without changing business code.
- **JSON logs:** machine-readable records make concurrent services easier to
  distinguish during later demonstrations.

## Files created or modified

- `README.md` - setup, layout, launch, testing, and current limitations.
- `.env.example` - configuration variable reference without secrets.
- `.gitignore` - excludes local databases, uploads, environments, caches, and
  temporary files.
- `requirements.txt` - records that Phase 0 has no third-party dependency.
- `common/` - validated settings, JSON logging, application errors, request IDs,
  UTC time helper, and placeholder lifecycle.
- `domain/models.py` - initial data-only domain model and enum definitions.
- `server/` - chat placeholder plus persistence protocols.
- `llm_server/` - independent LLM placeholder.
- `client/` - client placeholder.
- `scripts/start_*.cmd` - convenience launchers from any current directory;
  arguments such as `--once` are forwarded to the Python entry point.
- `tests/` - configuration, domain-invariant, and process smoke tests.
- `docs/requirements.md` - stories, permissions, ownership, and conventions.
- `docs/architecture.md` - baseline architecture and important tradeoffs.

## How the code works

Each entry point calls `load_settings()`, which reads and validates environment
variables. It then calls `configure_logging()` and writes a structured startup
record with its service and node identity. The chat and LLM placeholders wait
until interrupted; the client exits because it has no Phase 0 operation.
`--once` makes each process print its identity and exit for automated checks.

## Configuration and external prerequisites

Required: Python 3.11+. The convenience scripts use the Windows command shell.
There are no accounts, credentials, API keys, model downloads, firewall changes,
or external services required for Phase 0. `.env.example` documents overrides.

## Expected output and behavior

Each one-shot command produces a JSON line similar to:

```json
{"event":"service_started","service":"chat-server","node_id":"chat-node-1","phase":0,"placeholder":true}
```

Actual records also contain a UTC timestamp, severity, logger name, explicit
service identity fields, and the configured address. No socket is opened.

## Tests performed

The following commands were executed successfully on September 23, 2026:

```powershell
python -m compileall -q common domain server llm_server client tests
python -m unittest discover -s tests -v
```

Compilation completed with exit code 0. All 7 tests passed. They covered default
and overridden settings, invalid ports/log levels, UTC/expiry model invariants,
and subprocess startup identity for the chat, LLM, and client placeholders.
Each `.cmd` launcher was also run with `--once`; all three exited with code 0
and printed the expected service and node identity.

## Exact verification steps for the user

From the repository root:

```powershell
python --version
python -m unittest discover -s tests -v
python -m server --once
python -m llm_server --once
python -m client --once
.\scripts\start_chat.cmd --once
.\scripts\start_llm.cmd --once
.\scripts\start_client.cmd --once
```

Confirm that tests end with `OK` and each process emits
`"event":"service_started"`, the expected node ID, and
`"placeholder":true`. To verify long-running placeholders, start the chat and
LLM scripts in separate terminals and stop each with `Ctrl+C`.

## Known limitations, placeholders, mocks, and TODOs

- All three executables are clearly marked placeholders.
- No gRPC socket, protobuf contract, health endpoint, or metadata interceptor
  exists yet; these belong to Phase 1.
- Repository and unit-of-work definitions have no SQLite implementation or
  migration; those belong to Phase 2.
- Initial models do not implement business permissions or workflows.
- The LLM process loads no model and returns no generated answer.
- No `.env` parser is included; set environment variables in the shell.

## Explicitly out-of-scope functionality not implemented

Authentication, session behavior, channels, messaging, history, streaming,
presence, file transfer, administration behavior, LLM inference, gRPC,
concurrency behavior, retries/idempotency storage, Raft, leader election,
replication, commit, failover, and recovery are not implemented in Phase 0.
