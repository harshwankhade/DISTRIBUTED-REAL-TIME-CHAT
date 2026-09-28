# Architecture - Phase 4 / Milestone 1

## Current executable architecture

```text
clients / tests
      |
      | gRPC + request ID + bearer token
      v
chat transport services
  Auth / Channel / Chat / Presence / File / AI gateway
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
  users, sessions, channels, memberships, join requests,
  messages, file metadata, idempotency keys
  |
  +--> stable references to file bytes under FILE_STORAGE_PATH

AI gateway -- bounded authorized context + deadline --> independent LLM gRPC service
                                                     |
                                                     +--> deterministic mock, or
                                                     +--> llama.cpp + local Qwen GGUF

Tkinter clients --> all user-facing RPCs on the chat server
```

## Layer responsibilities

- **gRPC layer:** validates wire shapes, reads metadata, invokes application
  services, maps safe errors to gRPC statuses, and streams events/file chunks.
- **Application layer:** owns authentication, permissions, channel/message/file
  rules, idempotency, presence behavior, and command creation.
- **Channel ownership:** a channel's existing `created_by` is its owner. The
  creator is a member from creation. Nonmembers submit persisted join requests;
  only the owner may approve or reject them or directly manage members. The
  retired global AdminService is not registered. The GUI polls pending requests
  rather than claiming a durable notification stream. Members may view the
  roster; only the owner sees removal controls. Owner deletion removes the
  channel and database-linked state in one transaction.
- **Event layer:** fans out live message and presence events inside one process.
  It is not a durable queue; message history is the reconnect recovery path.
- **Repository layer:** owns SQL and maps rows to domain objects.
- **Storage layer:** keeps file bytes outside SQLite using generated names while
  SQLite owns checksums, authorization linkage, and stable references.
- **AI gateway:** authenticates the requester, verifies channel membership,
  reads only server-owned messages for that channel/time range, enforces
  context limits, and makes a deadline-bound gRPC call to Node 1.
- **LLM process (Node 1):** validates the bounded context and performs inference.
  It has no database, token-validation, file, or state-mutation access.
- **Client layer:** a lightweight Tkinter GUI uses background threads for live
  streams and inference so the desktop event loop stays responsive.

Message rows continue to store the stable sender user ID. Message reads join
the users table to add the sender's username to transport responses, while new
live messages use the already-authenticated user's username. This avoids
duplicating display data in the message table and lets the GUI show readable
names for both history and live events.

## LLM trust and failure boundary

Clients invoke `LLMService` on the chat-server address. Although the v1 request
shape contains `requester_id` and `authorized_context` for the downstream call,
the gateway deliberately ignores both fields from an external client. Identity
comes only from the bearer session, and context comes only from the repository
after a membership check. Node 1 receives that already-filtered subset through
gRPC and cannot expand it.

Context is bounded by `LLM_MAX_CONTEXT_MESSAGES`,
`LLM_MAX_CONTEXT_CHARS`, and an optional summary time range. The client call to
Node 1 has `LLM_REQUEST_TIMEOUT_SECONDS`. Connection failures, model failures,
and deadline expiry produce an explicit safe fallback response; they do not
make ordinary chat RPCs depend on LLM availability. Generated text is not
written back to chat unless a user chooses to send it.

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
streams recheck membership before each emitted event or keepalive, so removal
or deletion closes an old subscription.
Slow consumers may lose live events when their queue is full; they can recover
durable messages with `GetHistory`. Stored uploaded bytes are not removed by
channel deletion; their metadata is deleted, so app downloads cannot resolve
them.

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

Members can page through existing attachment metadata for a channel. Repository
reads join the uploader's user record so the GUI can display a username without
duplicating it in the files table. A successful new upload publishes a
process-local file event containing metadata only. The GUI merges message and
file metadata by UTC creation time and embeds a checksum-verifying **Download**
button. Missed live events are recovered from the durable file listing.

## Future Raft compatibility

Durable message and file-metadata writes are represented by immutable commands.
IDs, timestamps, and checksums are fixed before repository application. Phase 4
still commits to one local SQLite database: there is no replicated log, leader,
majority acknowledgement, failover, or cross-node stream fan-out.
