# Architecture - Phase 3 Baseline

## Current executable architecture

```text
clients / tests
      |
      | gRPC + request ID + bearer token
      v
chat transport services
  Auth / Channel / Admin / Chat / Presence / File
      |
      v
application services + immutable commands
      |                    |
      |                    +--> process-local event broker --> server streams
      v
unit of work + repositories       transient presence tracker
      |                                   |
      v                                   +--> heartbeat timeout
per-server SQLite
  users, sessions, channels, messages, file metadata, idempotency keys
      |
      +--> stable references to file bytes under FILE_STORAGE_PATH

independent LLM gRPC skeleton (no model behavior yet)
```

## Layer responsibilities

- **gRPC layer:** validates wire shapes, reads metadata, invokes application
  services, maps safe errors to gRPC statuses, and streams events/file chunks.
- **Application layer:** owns authentication, permissions, channel/message/file
  rules, idempotency, presence behavior, and command creation.
- **Event layer:** fans out live message and presence events inside one process.
  It is not a durable queue; message history is the reconnect recovery path.
- **Repository layer:** owns SQL and maps rows to domain objects.
- **Storage layer:** keeps file bytes outside SQLite using generated names while
  SQLite owns checksums, authorization linkage, and stable references.

## Durable messaging and idempotency

`SendMessageCommand` receives its ID and UTC timestamp before persistence. The
database uniquely constrains `(sender_id, client_request_id)`. Retrying the same
content returns the original message; reusing the key for different content is
rejected. History uses a database sequence cursor rather than a shifting offset,
so new messages do not duplicate or skip items in an existing pagination walk.

SQLite permits one writer. Phase 3 command transactions use `BEGIN IMMEDIATE`
to reserve that writer slot before read-then-write logic, avoiding transaction
upgrade races between concurrent gRPC workers. This is local serialization, not
distributed ordering or Raft consensus.

## Live streams

After authorization, each subscriber receives a bounded in-memory queue. Chat
streams filter by channels whose membership was verified when the stream began.
Slow consumers may lose live events when their queue is full; they can recover
durable messages with `GetHistory`. Membership changes during an already-open
stream take effect after reconnect in this phase.

## Presence

Presence is deliberately transient. A valid session heartbeat records a UTC
last-seen time per session. A user is online while any session has a recent
heartbeat and becomes offline once all heartbeats exceed
`PRESENCE_TIMEOUT_SECONDS`. Expiry is evaluated by presence reads and active
presence streams. Presence is not stored in SQLite or intended for the Raft log.

## File storage

Uploads receive a header followed by byte chunks. Before accepting metadata the
server checks authentication, channel membership, active-channel state, safe
filename, MIME allowlist, size limit, optional message linkage, and SHA-256.
Chunks go to a `.part` temporary file and are atomically renamed only after size
and checksum verification. Invalid or interrupted uploads remove the temporary
file. Generated storage names prevent traversal and collisions.

File metadata and upload idempotency keys are durable in SQLite. File bytes are
not stored in SQLite and will not be copied into the future Raft log. Downloads
recheck membership and stored-file integrity before streaming chunks.

## Future Raft compatibility

Durable message and file-metadata writes are represented by immutable commands.
IDs, timestamps, and checksums are fixed before repository application. Phase 3
still commits to one local SQLite database: there is no replicated log, leader,
majority acknowledgement, failover, or cross-node stream fan-out.
