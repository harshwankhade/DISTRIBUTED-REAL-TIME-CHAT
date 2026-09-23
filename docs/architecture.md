# Architecture - Phase 0 Baseline

## Current executable shape

Phase 0 establishes three independently runnable Python processes:

```text
client placeholder
    (no RPC yet)
chat-server placeholder ---- future gRPC ---- LLM-server placeholder
    |
    `---- future repository adapter ---- per-server SQLite
```

Each process loads centralized environment configuration and emits JSON logs
containing service and node identity. The two server placeholders then wait for
shutdown. They do not bind a port, exchange data, or claim network availability.

## Target process boundaries

- **Client:** user interaction, subscriptions, uploads/downloads, and concurrent
  test clients. It never accesses the database directly.
- **Chat application server:** authentication, authorization, business rules,
  persistence coordination, and future Raft command submission.
- **LLM server:** independent inference endpoint. It receives bounded authorized
  context through gRPC and cannot directly mutate chat state.
- **SQLite adapter:** Milestone 1 local persistence behind repository and
  unit-of-work interfaces.
- **Raft module:** absent until Phase 5. It will later order deterministic durable
  commands without changing client-facing contracts.

## Layering decisions

```text
transport (future gRPC services)
        |
application/business logic (future phases)
        |
repository + unit-of-work ports
        |
SQLite adapter (Phase 2)
```

Transport, business rules, and persistence are kept separate. The repository
interfaces are intentionally small in Phase 0; domain-specific query methods
will be added only when a phase proves they are necessary.

## Initial domain vocabulary

`domain.models` contains immutable, data-only models for `User`, `Session`,
`Channel`, `ChannelMember`, `Message`, `FileMetadata`, `Presence`,
`ConversationContext`, and `AuditEvent`. They validate basic identity and UTC
timestamp invariants but contain no business workflows.

`RaftLogEntry` and `NodeState` are intentionally not present because Raft belongs
to Milestone 2.

## Persistence decision

SQLite is selected for the single-server Milestone 1 implementation because it
is built into Python, transactional, easy to reset for a classroom demo, and
requires no external database service. Each chat server will own a separate
database file. A shared SQLite file across nodes is not an acceptable substitute
for Raft replication.

The tradeoff is limited multi-process write scalability. That is acceptable for
Milestone 1 and the repository boundary prevents SQLite-specific details from
leaking into RPC contracts or business rules.

## Configuration and observability

All environment-specific values are loaded once through `common.config`.
Settings validate ports, log levels, and required identity text. Defaults are
local-development values, not business-logic constants.

All processes use one-line JSON logs. Stable fields include UTC timestamp,
severity, logger, event, service, and node ID. Future phases may add request ID,
user/channel identifiers when safe, and Raft term/role only after Raft exists.

## Future compatibility without premature implementation

- Message models already distinguish `client_request_id` from server message ID.
- Repository transactions can later sit behind deterministic application
  commands and Raft apply order.
- File metadata separates byte storage from durable references.
- Conversation context records the requester and channel boundary needed for
  later privacy filtering.
- Ports and node identities can differ per process/node without code changes.

These are compatibility seams only. Phase 0 implements no idempotency store,
message command, file transfer, context builder, or consensus behavior.

