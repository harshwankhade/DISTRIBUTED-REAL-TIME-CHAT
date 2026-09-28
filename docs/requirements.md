# Requirements, Roles, and Conventions

## Purpose

The final product is a distributed real-time chat and collaboration system.
This document began as the Phase 0 requirements and records the current
owner-based permission policy approved after Milestone 1.

## Users and permissions

### Normal user stories

A registered user can:

- Register, log in, log out, and use an expiring session.
- See registered users and discover channels; request to join a channel.
- Read history and send messages only in channels they belong to.
- Receive live message and presence events for authorized channels.
- Upload and download permitted files without reading another channel's files.
- See online, offline, and last-seen information allowed by policy.
- Request smart replies, summaries, and suggestions using only conversation
  content they are authorized to read.

A user cannot change another account, read a channel before approval, or manage
membership in a channel they do not own.

### Channel owner stories

The user who creates a channel becomes its owner and first member. The owner can:

- See pending join requests and approve or reject them.
- Add or remove members, except that the owner cannot remove themself.
- Permanently delete their own channel, including its memberships, messages,
  pending requests, and file records.

The separate global administrator account and its RPC service are retired.
Ordinary users can create their own channels; creating one does not grant
privileges over other channels or users.

## Permission matrix

| Capability | Registered user | Channel owner (own channel) |
|---|---:|---:|
| Register/log in/out | Own account | Own account |
| List/request/leave channels | Yes / cannot leave owned channel | Same |
| Read/send channel content | Member only | Member only |
| Upload/download files | Member only | Member only |
| Request LLM assistance | Authorized context only | Authorized context only |
| Create channel | Yes, becomes owner | Yes |
| View channel roster | Member only | Yes |
| Approve join or manage members | No | Yes |
| Delete channel and its history | No | Yes |
| Enable/disable users or change roles | No | No |

There is no cross-channel override: ownership of one channel grants no access
to any other channel. Channel archiving is not exposed in the current UI/API.
Deleting a channel does not delete uploaded bytes from local disk; those bytes
become unreferenced and inaccessible through the app.

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

Phase 1 provides client/server metadata interceptors. Business-level duplicate
detection is still deferred until the applicable feature phase.

Bearer tokens are validated against persisted sessions. Tokens are revoked on
logout, and expired or disabled-account sessions are rejected. Disabling an
account is no longer available through the public RPC surface.

## Timestamp convention

- Persisted and transmitted timestamps represent UTC instants.
- Python values must be timezone-aware.
- Logs and human-readable interchange use ISO 8601 with a `Z` suffix.
- A timestamp or generated ID needed by a future replicated command must be
  chosen before replication, never independently during state-machine apply.

## Status and error convention

Application failures use a stable safe code and message. Phase 1 maps transport
validation and skeleton failures to gRPC statuses without exposing stack traces
or secrets.

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
