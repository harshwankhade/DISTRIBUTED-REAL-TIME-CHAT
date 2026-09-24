# Architecture - Phase 2 Baseline

## Current executable architecture

```text
client / tests
      |
      | gRPC + request ID + bearer token
      v
chat transport services
  Auth / Channel / Admin       Chat / Presence / File skeletons
      |                              (authentication only)
      v
application services
  authentication / sessions / authorization / channel rules
      |
      v
unit of work + repositories
      |
      v
per-server SQLite database

independent LLM gRPC skeleton (no model behavior yet)
```

## Layer responsibilities

- **gRPC layer:** validates wire-level required fields, reads metadata, invokes
  application services, and maps safe application errors to gRPC statuses.
- **Application layer:** owns authentication, permissions, token lifecycle,
  channel rules, and transaction-sized operations. It does not import protobuf.
- **Repository layer:** owns SQL and maps rows to domain objects.
- **Database layer:** creates connections and applies ordered migrations once.
- **Security layer:** owns password and session-token primitives.

This separation prevents gRPC handlers from becoming the persistence model and
allows future committed commands to invoke application/repository behavior
without changing client contracts.

## Persistence and transactions

Each chat server uses its own configured SQLite file. Every application
operation opens one connection and transaction through `SQLiteUnitOfWork`.
Writes explicitly commit; exceptions and uncommitted operations roll back.
Foreign keys, busy timeout, and WAL mode are enabled on file databases.

`001_initial.sql` creates users, sessions, channels, memberships, indexes, and
the migration record. Migration application is repeatable. A shared SQLite file
between future Raft nodes is explicitly not the replication design.

## Authentication model

Passwords use salted `scrypt` with versioned parameters stored in the encoded
hash. Login performs a dummy hash check for unknown users to reduce obvious
username timing differences.

Successful login returns a random opaque token. Only a SHA-256 digest is stored.
The request interceptor extracts `authorization: Bearer <token>` without logging
the token. Application authentication verifies that the session exists, is not
revoked or expired, and belongs to an active user.

Disabling a user revokes all current sessions in the same transaction. Logout
revokes the current session. There is no refresh-token flow.

## Authorization and channel rules

- Admin RPCs require an authenticated active administrator.
- Creating channels through `ChannelService` is also administrator-only.
- Active normal users can list active channels and self-join them.
- Leaving requires existing membership.
- Admins can view archived channels and manage members of active channels.
- Archived channels reject joins and membership changes.

The current public-channel assumption avoids inventing a private-channel model
before it is requested.

## Future Raft compatibility

Durable write inputs are represented by immutable command objects containing
IDs and timestamps generated before persistence. This prepares a clean command
boundary for later deterministic replication. These commands are currently
executed in one local SQLite transaction only; there is no log, leader,
replication, majority acknowledgement, or failover.

## Concurrency and failures

gRPC worker threads use separate SQLite connections and transactions. SQLite's
locking plus busy timeout protects local concurrent access. Requests can still
fail with normal gRPC/database errors; distributed retries and duplicate-request
handling belong to later phases.

