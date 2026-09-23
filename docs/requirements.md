# Requirements, Roles, and Conventions

## Purpose

The final product is a distributed real-time chat and collaboration system.
This document freezes the product expectations and cross-cutting conventions
needed for Phase 0. It does not claim that the features are implemented.

## Users and permissions

### Normal user stories

A normal user will eventually be able to:

- Log in, log out, and use an expiring session.
- List channels they may discover and join or leave permitted channels.
- Read history and send messages only in channels they belong to.
- Receive live message and presence events for authorized channels.
- Upload and download permitted files without reading another channel's files.
- See online, offline, and last-seen information allowed by policy.
- Request smart replies, summaries, and suggestions using only conversation
  content they are authorized to read.

A normal user must not manage other accounts, change another user's role,
archive channels without permission, or add/remove arbitrary members.

### Administrator stories

An administrator will eventually be able to:

- Create users and enable or disable accounts.
- Assign allowed roles according to the chosen security policy.
- Create and archive channels.
- Add or remove channel members.
- Inspect safe audit events needed to explain administrative changes.

Administrators remain subject to authentication, validation, audit, and privacy
rules. Admin status is not permission to bypass service boundaries.

## Permission matrix

| Capability | Normal user | Administrator |
|---|---:|---:|
| Log in/out | Own account | Own account |
| List/join/leave channels | Allowed channels / self | Allowed channels / self |
| Read/send channel content | Member only | Member only by default |
| Upload/download files | Member only | Member only by default |
| Request LLM assistance | Authorized context only | Authorized context only |
| Create/archive channels | No | Yes |
| Add/remove members | No | Yes |
| Enable/disable users | No | Yes |
| Change user roles | No | Yes |

Whether administrators may automatically read every channel is deliberately
answered **no by default**. A later phase may refine this policy only with an
explicit requirement and privacy impact explanation.

## Data ownership and persistence

- The chat application owns users, sessions, channels, memberships, messages,
  file metadata, presence records, idempotency records, and audit events.
- During Milestone 1, one chat server will use its own SQLite database.
- Persistence is accessed through repository and unit-of-work interfaces so
  application code is not coupled directly to SQLite.
- File bytes will be stored outside the database/Raft log; the application owns
  metadata and a stable storage reference.
- The independent LLM service owns model configuration only. It does not own or
  mutate chat state and receives bounded, authorized context per request.
- Presence heartbeats and live subscriptions are transient and will not enter
  the future Raft log.

Phase 0 defines these boundaries but does not create a schema or store data.

## Request and correlation IDs

- Every remote request will carry a non-empty opaque request ID.
- If a trusted client does not supply one, the receiving boundary may create a
  UUID and return/log it.
- The same request ID follows downstream calls for tracing.
- A separate `client_request_id` identifies retryable state-changing commands
  and later supports idempotency.
- IDs are strings at service boundaries. Code must not infer ordering from them.

Phase 0 provides an ID helper; metadata extraction belongs to Phase 1.

## Timestamp convention

- Persisted and transmitted timestamps represent UTC instants.
- Python values must be timezone-aware.
- Logs and human-readable interchange use ISO 8601 with a `Z` suffix.
- A timestamp or generated ID needed by a future replicated command must be
  chosen before replication, never independently during state-machine apply.

## Status and error convention

Application failures use a stable safe code and message. Phase 1 will map them
to the matching gRPC status without exposing stack traces or secrets.

| Application code | Intended meaning |
|---|---|
| `INVALID_ARGUMENT` | Input is malformed or violates a stated constraint |
| `UNAUTHENTICATED` | Credentials/session are missing or invalid |
| `PERMISSION_DENIED` | Identity is known but the action is forbidden |
| `NOT_FOUND` | Authorized caller cannot find the requested resource |
| `ALREADY_EXISTS` | A unique resource already exists |
| `CONFLICT` | Current state prevents the requested transition |
| `DEADLINE_EXCEEDED` | Operation exceeded its deadline |
| `UNAVAILABLE` | Required service or leader cannot currently respond |
| `NOT_IMPLEMENTED` | Contract exists but the current phase has no behavior |
| `INTERNAL` | Unexpected server failure with safe client wording |

Validation errors are deterministic. Logs may contain diagnostic details, but
client responses must remain safe and include the request ID.

## Failure and retry assumptions

- Remote calls can time out, be duplicated, or complete after the client stops
  waiting; later state-changing RPCs therefore need idempotency.
- A successful durable write must not be claimed until the applicable phase's
  persistence/consensus guarantee is actually satisfied.
- Partial failure of the LLM service must not stop normal chat behavior.
- Raft behavior, majority commit, failover, and recovery are future work and are
  not simulated in this scaffold.

