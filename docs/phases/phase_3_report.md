# Phase 3 - Messaging, Presence, and File Sharing

**Status:** Complete

## Scope completed

Phase 3 adds the main collaboration behavior to one chat server: durable channel
messages, cursor-paginated history, live message streams, heartbeat presence,
presence streams, and authorized chunked file upload/download. Message creation
and file-metadata creation are expressed as immutable application commands for
future Raft integration.

LLM behavior and Raft were not implemented.

## Assumptions

- Only channel members can read history, subscribe to channel messages, upload,
  or download files. Administrators do not bypass membership.
- Archived channels are readable by existing members but reject new messages
  and uploads.
- Presence is process-local and transient. It is not restored after restart.
- A user is online while at least one authenticated session sends heartbeats
  within the configured timeout.
- File bytes belong to local filesystem storage. Only metadata and a stable
  reference belong in future replicated state.
- MIME type is a declared allowlisted value; Phase 3 does not inspect file
  signatures or run malware scanning.

## What was implemented

- Server-generated UUID message IDs and timezone-aware UTC timestamps.
- SQLite message history with stable descending sequence-cursor pagination.
- Message idempotency using the unique `(sender_id, client_request_id)` key.
- Conflict detection when an idempotency key is reused with different content.
- A thread-safe event broker for live message and presence fan-out.
- Authenticated channel subscriptions with idle keepalives and cancellation.
- Empty-channel subscriptions expose keepalives only, allowing the smoke client
  to verify authenticated streaming without requiring a pre-created channel.
- Per-session heartbeats, online/offline state, last-seen time, and timeout
  transitions through a presence stream.
- Chunked uploads to temporary files with safe names, size/type validation,
  optional message linkage, SHA-256 validation, and atomic final rename.
- Chunked downloads that recheck membership and stored-file integrity.
- File-upload idempotency and durable SQLite file metadata.
- Phase 3 configuration, migration, repository coverage, concurrency tests, and
  end-to-end gRPC acceptance tests.

## Distributed-systems concepts involved

### Idempotency and retries

A client may retry after a timeout even when the first request succeeded.
`client_request_id` lets the server return the first message/file result instead
of creating a duplicate. The deduplication key and result are durable in SQLite.
This is single-server idempotency; Phase 6 must put it in replicated state.

### Durable state versus ephemeral events

Messages and file metadata survive restart. Live stream queues and presence
heartbeats do not. If a client misses a live message, it recovers through
history. This avoids claiming that the in-memory broker is a durable queue.

### Concurrency and local ordering

gRPC uses multiple worker threads and separate SQLite connections. Write
commands use an immediate SQLite transaction so concurrent read-then-write
operations wait for the local writer slot instead of failing during a deferred
transaction upgrade. SQLite sequence values provide local history order only;
they are not Raft log indexes or distributed consensus.

### Failure-safe streaming files

Uploads are processed incrementally rather than held in memory. A partial,
oversized, or checksum-invalid upload removes its `.part` file and creates no
metadata row. Generated storage names prevent client-controlled traversal.

## Architecture and design decisions

- Existing v1 protobuf contracts were sufficient, so no field numbers or RPCs
  changed and stubs did not need regeneration.
- The application layer remains independent of protobuf. Transport handlers
  convert protobuf requests to ordinary values and application commands.
- History uses a sequence cursor instead of offset pagination, preventing new
  messages from shifting the next page during a pagination walk.
- One bounded queue per subscriber prevents a slow stream from growing memory
  forever. If it overflows, oldest live events may be dropped; durable messages
  remain recoverable through history.
- Presence uses one record per active session so another recent session keeps a
  user online when one client disconnects.
- Downloads verify checksum before streaming. This reads the file once for
  validation and again for transfer, trading extra I/O for avoiding delivery of
  known-corrupt content.

## Files created or modified

```text
.env
.env.example
README.md
common/config.py
client/grpc_client.py
client/main.py
docs/api_contracts.md
docs/architecture.md
docs/phases/phase_3_report.md
server/application/chat.py
server/application/commands.py
server/application/files.py
server/application/__init__.py
server/application/presence.py
server/events.py
server/grpc_server.py
server/main.py
server/migrations/002_messaging_files.sql
server/repositories/sqlite.py
server/services.py
tests/test_config.py
tests/test_grpc_skeleton.py
tests/test_phase3_collaboration.py
tests/test_placeholders.py
tests/test_repositories.py
```

The migration adds `messages` and `files`. Application modules implement rules,
`events.py` owns process-local fan-out, repository changes map durable records,
and `services.py` exposes the behavior through the existing gRPC contracts.

## How the code works

`SendMessage` authenticates the session, verifies active-channel membership,
creates a command, and inserts it once. The committed message is then published
to matching stream subscribers. `GetHistory` reads a bounded page using a
sequence cursor.

`Heartbeat` updates a session heartbeat. Active presence streams periodically
expire stale heartbeats and publish an offline transition when no recent
session remains.

`UploadFile` validates its header and streams chunks into a temporary file while
counting bytes and hashing. Only a valid complete upload is renamed and given a
metadata row. `DownloadFile` verifies access and integrity, sends metadata
first, and then streams configured-size chunks.

## Configuration and external prerequisites

No new dependency or external service is required. Important settings are:

- `MAX_MESSAGE_LENGTH` (default `4000`)
- `PRESENCE_TIMEOUT_SECONDS` (default `15`)
- `FILE_STORAGE_PATH` (default `uploads/chat-node-1`)
- `MAX_FILE_SIZE_BYTES` (default `10485760`)
- `FILE_CHUNK_SIZE_BYTES` (default `65536`)
- `ALLOWED_FILE_TYPES` (comma-separated MIME allowlist)

The server creates the upload directory when the first upload begins. Existing
Phase 2 databases are upgraded automatically with `002_messaging_files.sql`.

## Expected output and behavior

- Three authenticated members can send concurrently and see exactly one
  durable result for each `client_request_id`.
- Members can page history and receive new messages without polling.
- Non-members receive `PERMISSION_DENIED` for history, subscriptions, and files.
- A heartbeat changes presence to online; lack of heartbeats changes it to
  offline after the configured timeout.
- Valid downloads reproduce the uploaded bytes and SHA-256 checksum.
- Interrupted, oversized, unsafe, disallowed, or checksum-invalid uploads fail
  without leaving partial files or metadata.

## Tests performed

The final verification commands were run on September 26, 2026:

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
```

All 37 automated tests passed. Phase 3 coverage includes concurrent three-client
messaging, retry deduplication, paginated history, live delivery, non-member
denials, online/offline stream transitions, chunked transfer, repeat upload,
download checksum equality, invalid checksum cleanup, interrupted-upload
cleanup, migration repeatability, and restart persistence of messages and file
metadata. Existing Phase 0-2 and LLM-skeleton tests also remain green.

## Exact verification steps for the user

From the repository root:

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.\scripts\migrate.cmd
.venv\Scripts\python -m unittest tests.test_phase3_collaboration -v
.venv\Scripts\python -m unittest discover -s tests -v
```

Start the chat server separately with:

```powershell
.\scripts\start_chat.cmd
```

The acceptance scenarios are fully reproducible by
`tests.test_phase3_collaboration`, which starts an isolated server, database,
upload directory, and multiple real gRPC clients.

## Known limitations, placeholders, mocks, and TODOs

- Live event delivery is best-effort and process-local; reconnecting clients
  must use history to recover messages.
- An already-open chat stream does not re-evaluate membership until reconnect.
- Presence expiry is evaluated while presence is queried or streamed; there is
  no separate always-running sweeper thread.
- Presence is lost on server restart, by design.
- MIME validation trusts the declared type and there is no malware scanning.
- A process crash in the narrow interval after final file rename but before
  metadata commit can leave an orphan file for future cleanup tooling.
- The Phase 3 client remains a smoke-test client rather than a full interactive
  terminal UI.
- The LLM server remains a Phase 1 skeleton.

## Explicitly out-of-scope functionality not implemented

Local-model inference, smart replies, summaries, suggestions, LLM context
filtering, Raft roles/logs/elections, replicated idempotency, majority commit,
multi-server stream fan-out, leader failover, follower recovery, and distributed
file replication were not implemented.
