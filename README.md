# Distributed Real-time Chat and Collaboration Tool

This repository is being built one approved phase at a time for a distributed
systems course project. Phase 0 provides the documented architecture, initial
domain vocabulary, shared configuration and logging, persistence boundaries,
and runnable process placeholders. It does **not** provide a chat system yet.

## Current status

- Completed: Phase 0 - requirements and repository scaffold
- Next, only when explicitly requested: Phase 1 - protobuf contracts and gRPC
  service skeletons
- Not implemented: authentication, channels, messaging, files, presence, LLM
  inference, networking, replication, Raft, or fault tolerance

## Requirements

- Python 3.11 or newer
- Windows command shell for the convenience launch scripts

Phase 0 has no third-party Python dependency. `requirements.txt` records that
decision; gRPC dependencies belong to Phase 1.

## Repository layout

```text
.
|-- client/                 # Runnable client placeholder
|-- common/                 # Configuration, JSON logging, errors, metadata
|-- docs/
|   |-- architecture.md     # Process boundaries and future-compatible design
|   |-- requirements.md     # User stories, permissions, and conventions
|   `-- phases/
|       `-- phase_0_report.md
|-- domain/                 # Data-only initial domain models
|-- llm_server/             # Runnable independent LLM placeholder
|-- scripts/                # PowerShell process launchers
|-- server/
|   `-- repositories/       # Persistence and transaction interfaces
|-- tests/                  # Standard-library unit and smoke tests
|-- .env.example            # Environment-variable reference
|-- AGENTS.md               # Phase and implementation rules
`-- requirements.txt
```

Directories for protobuf definitions and Raft are intentionally absent because
those phases have not started.

## Configuration

Configuration is read from process environment variables. Defaults are safe for
local development and are listed in `.env.example`. That file is a reference;
Phase 0 does not add a `.env` parsing dependency.

Example PowerShell overrides:

```powershell
$env:CHAT_NODE_ID = "chat-node-local"
$env:CHAT_PORT = "51051"
$env:LOG_LEVEL = "DEBUG"
```

Ports and node identities are resolved by `common.config`; they are not embedded
in business logic. There are no credentials in Phase 0.

## Run the placeholders

From the repository root, use three terminals:

```powershell
.\scripts\start_chat.cmd
```

```powershell
.\scripts\start_llm.cmd
```

```powershell
.\scripts\start_client.cmd
```

The chat and LLM placeholders print structured service identity and wait until
`Ctrl+C`. The client prints its identity and exits. No port is bound and no RPC
is available yet. Use one-shot mode for a quick check:

```powershell
python -m server --once
python -m llm_server --once
python -m client --once
```

Expected output is one JSON log record per process containing
`"event":"service_started"`, the service/node identity,
`"phase":0`, and `"placeholder":true`.

## Run the Phase 0 checks

```powershell
python -m compileall -q common domain server llm_server client tests
python -m unittest discover -s tests -v
```

The tests validate configuration defaults and overrides, invalid configuration,
basic domain invariants, and startup identity for all three placeholders.

## Documentation

- [Requirements and conventions](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Phase 0 report](docs/phases/phase_0_report.md)

## Safety and limitations

The placeholder processes must not be interpreted as working distributed
services. gRPC communication begins in Phase 1, chat persistence begins in
Phase 2, collaboration features begin in Phase 3, the separate LLM behavior is
implemented in Phase 4, and Raft begins in Phase 5.
