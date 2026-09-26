# Distributed Real-time Chat and Collaboration Tool

This Python/gRPC project is built one approved phase at a time for a distributed
systems course. Phase 3 provides a working single-server collaboration system:
access control, channel messages and history, live event streams, heartbeat
presence, and authorized chunked file transfer.

## Current status

- Completed: Phase 0 - requirements and repository scaffold
- Completed: Phase 1 - protobuf contracts and gRPC skeletons
- Completed: Phase 2 - users, sessions, channels, and administration
- Completed: Phase 3 - messaging, presence, and file sharing
- Next only when explicitly requested: Phase 4 - separate local LLM service
- Not implemented: LLM behavior, Raft, replication, failover, or recovery

## Setup

Requirements:

- Python 3.11 or newer
- Windows command shell for convenience scripts

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\scripts\generate_stubs.cmd
```

## Configuration

Copy the example file once and edit `.env` with your local values:

```powershell
Copy-Item .env.example .env
```

The processes automatically load `.env` from the repository root. Variables
already set in the process environment take precedence, which allows deployment
or one-off overrides without editing the file. `.env` is ignored by Git; do not
commit it. Important Phase 3 settings are:

- `CHAT_DATABASE_PATH` - this server's SQLite database file
- `SESSION_TTL_SECONDS` - login-token lifetime
- `CHAT_HOST` and `CHAT_PORT` - chat gRPC listen address
- `GRPC_WORKERS`, `RPC_TIMEOUT_SECONDS`, and `SHUTDOWN_GRACE_SECONDS`
- `MAX_MESSAGE_LENGTH` - accepted message length
- `PRESENCE_TIMEOUT_SECONDS` - heartbeat expiry interval
- `FILE_STORAGE_PATH`, `MAX_FILE_SIZE_BYTES`, and `FILE_CHUNK_SIZE_BYTES`
- `ALLOWED_FILE_TYPES` - comma-separated accepted MIME types

The example contains no credentials. Put local-only seed and smoke-test
passwords in `.env`, and do not reuse real account passwords.

## Migrate and seed the database

Apply migrations:

```powershell
.\scripts\migrate.cmd
```

For a non-interactive local seed, fill `SEED_ADMIN_PASSWORD` and
`SEED_SAMPLE_PASSWORD` in `.env`, then run:

```powershell
.\scripts\seed_data.cmd
```

The default identities are one `admin` user and sample users `alice` and `bob`.
If password variables are absent, the command prompts without echoing input.
Running the command again skips existing users rather than duplicating them.

## Run the system

Start the chat server:

```powershell
.\scripts\start_chat.cmd
```

The independent LLM server remains a Phase 1 skeleton and may be started
separately when needed:

```powershell
.\scripts\start_llm.cmd
```

To run the transport smoke client against a seeded account:

```powershell
.\scripts\start_client.cmd --smoke
```

Set `SMOKE_USERNAME` and `SMOKE_PASSWORD` in `.env` first. For `alice`, use the
same value as `SEED_SAMPLE_PASSWORD`.

The smoke test performs health, real login, authenticated event-stream
keepalive, and stream cancellation. Stop servers with `Ctrl+C`.

## Implemented behavior through Phase 3

- Passwords are salted and hashed with `scrypt`; plaintext passwords are never
  stored.
- Session tokens are generated with `secrets`, returned once, and stored only as
  SHA-256 hashes.
- Sessions expire, can be logged out, and are revoked when a user is disabled.
- Admins can create users, enable/disable users, change roles, create/archive
  channels, and add/remove channel members.
- Active users can list channels, join active channels, and leave channels they
  belong to.
- Normal users cannot call administrator RPCs.
- Archived channels reject joins and membership changes.
- SQLite migrations and transactions preserve state across process restarts.
- Members can send idempotent messages, page through durable history, and
  receive new messages over a server stream.
- Heartbeats mark sessions online; users become offline after the configured
  timeout and presence changes are streamed.
- File uploads and downloads are chunked. Uploads validate membership,
  filename, type, size, message linkage, and SHA-256 checksum.
- File metadata is durable in SQLite while file bytes are stored separately.
- Repeated message and upload `client_request_id` values return the original
  result rather than creating duplicates.

Current assumption: every non-archived channel is discoverable and self-joinable
by active users. Private/invite-only channels have not been requested.

## Tests

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
```

Tests use temporary databases and ephemeral ports. They do not modify the
configured development database.

## Important documentation

- [Current architecture](docs/architecture.md)
- [v1 API contracts](docs/api_contracts.md)
- [Phase 2 report](docs/phases/phase_2_report.md)
- [Phase 3 report](docs/phases/phase_3_report.md)
- [Requirements and permissions](docs/requirements.md)

## Security and distributed-systems limitations

Local gRPC connections are currently plaintext. There is no password-reset or
token-refresh flow, rate limiting, audit-event persistence, LLM behavior, or
Raft. Live streams and presence are process-local; clients recover durable
messages through history after reconnecting. SQLite is local to one chat server
and must never be mistaken for replicated state or consensus.
