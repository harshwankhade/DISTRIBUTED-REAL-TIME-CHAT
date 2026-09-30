# Distributed Real-time Chat and Collaboration Tool

This Python/gRPC application supports authenticated
multi-user channels, live messages, history, presence, files, channel-owner management,Band three local-AI tools. The chat application and Qwen LLM run as separate processes and communicate only through gRPC.


## Prerequisites

- Windows 10/11 and Python 3.11 or newer
- About 3 GB free disk space for the virtual environment and model
- Acceptance of the Qwen2.5 model's `qwen-research` license
- No API key or cloud account is used

Tkinter ships with standard Windows Python. Check it with:

```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
```

## Fresh setup

Run these commands from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\scripts\install_llm_runtime.cmd
.\scripts\download_model.cmd
```

The last download is Qwen2.5-3B-Instruct Q4_K_M (about 2.1 GB). It resumes a
partial download. A fresh checkout runs with the built-in defaults and the
deterministic mock LLM; no `.env` file is required. To use the downloaded local
model, create a local `.env` file containing:

```dotenv
LLM_ADAPTER=local
LLM_MODEL_PATH=models/qwen2.5-3b-instruct-q4_k_m.gguf
```

Add other settings to `.env` only if you need to override the defaults.
Accounts are created
with **Register** in the GUI; no seeded administrator or password is required.
For the optional smoke client, set `SMOKE_USERNAME` and `SMOKE_PASSWORD`.
`.env`, `.env.example`, model files, uploads, databases, and logs are ignored
by Git.

The checked-in protobuf bindings are ready to use. Regenerate them after a
contract edit with `scripts\generate_stubs.cmd`.

## Configuration

All runtime values have validated defaults in `common/config.py`. An optional
local `.env` or process environment variable can override them; process
variables win. The important LLM values are:

- `LLM_ADAPTER=local` loads the downloaded GGUF; `mock` is deterministic and
  useful for tests or a quick evaluator run.
- `LLM_MODEL_PATH` is the local GGUF path.
- `LLM_THREADS=8` and `LLM_GPU_LAYERS=0` provide a CPU-first default suitable
  for the target 16 GB Intel laptop.
- `LLM_MAX_CONTEXT_MESSAGES` and `LLM_MAX_CONTEXT_CHARS` bound private context.
- `LLM_REQUEST_TIMEOUT_SECONDS` bounds chat-server calls to Node 1.
- `LLM_CONTEXT_WINDOW`, `LLM_MAX_OUTPUT_TOKENS`, and `LLM_TEMPERATURE` control
  local inference.

Chat, session, presence, file, address, and storage setting names and defaults
are defined in `common/config.py`. No port or credential is embedded in
business logic. `.env.example` is no longer distributed in new checkouts.

## Launch the complete Milestone 1 demo

The one-command path migrates the database, retires any legacy global-admin
account and channels it owned, starts the LLM and chat
servers as separate background processes, writes logs under `logs/`, and opens
the Tkinter client:

```powershell
.\scripts\start_milestone1.cmd
```

Open another user window with:

```powershell
.\scripts\start_client.cmd --gui
```

Stop the two background services with:

```powershell
.\scripts\stop_milestone1.cmd
```

You can also run each process in its own terminal:

```powershell
.\scripts\migrate.cmd
.\scripts\retire_legacy_admin.cmd
.\scripts\start_llm.cmd
.\scripts\start_chat.cmd
.\scripts\start_client.cmd --gui
```

The local model may take several seconds to load. The GUI remains responsive
while AI work runs. If Node 1 is unavailable or exceeds its deadline, the AI
panel reports a fallback while login, messaging, history, files, and presence
continue normally.

## Current Features

- Salted `scrypt` password hashes, opaque expiring session tokens, logout, and
  disabled-user enforcement.
- Self-registration, owner-created channels, durable join requests, and
  owner-only approval and member management.
- Persistent channel membership and join decisions in per-server SQLite.
- Owner-only permanent channel deletion and member-side roster viewing, with
  Remove buttons visible only to the owner.
- An owner-channel dropdown for adding a selected registered user without
  first selecting a channel in the channel list.
- Idempotent messages, stable history pagination, and live server streams.
- Human-readable sender usernames in message history and live chat, while
  retaining stable user IDs for authorization and persistence.
- Heartbeat-based online/offline transitions and last-seen data.
- Online/offline labels for registered users and selected-channel members,
  with a per-channel online count in the Tkinter GUI.
- Authorized chunked file transfer with size/type/path validation and SHA-256.
- Paginated channel attachments and live upload events with an in-chat
  **Download** button.
- A separate gRPC LLM process with swappable deterministic mock and local
  `llama-cpp-python` Qwen adapter.
- An authenticated context gateway: it ignores caller-supplied context, checks
  membership, loads only the selected channel/time range, applies message and
  character limits, and then calls Node 1 with a deadline.
- Tkinter desktop flows for registration/login, user and channel discovery,
  owner approvals, live chat, AI, files, and heartbeats.


## Known limitations

This is a single chat server with local plaintext gRPC and local SQLite. Live
streams and presence are process-local, and file bytes are stored on local
disk. Channel deletion removes database records, not uploaded bytes already on
disk. There is no password reset, TLS, rate limiting, durable audit log,
channel archive UI, or persistent AI output. Join
approval is shown by GUI polling, so the owner must keep their client open to
see the prompt; pending requests remain in SQLite. Presence labels are refreshed
about every five seconds and show `unknown` when the status RPC fails; offline
appears after the configured heartbeat timeout. Most importantly, there is no
Raft log, replication, majority commit, leader election, failover, or recovery;
none of those guarantees are claimed in Milestone 1.
