# Architecture - Phase 1 Baseline

## Current executable architecture

```text
client smoke CLI
    |
    | insecure local gRPC (Phase 1 transport only)
    v
chat gRPC skeleton                         independent LLM gRPC skeleton
  Health / Auth / Channel / Chat             Health / LLM
  Presence / File / Admin
    |
    `-- repository ports only; no adapter or database schema yet
```

The chat and LLM servers are separate processes with separate configured
addresses. This preserves the final service boundary without adding any model
runtime or business logic in Phase 1.

## Layering

```text
generated protobuf/gRPC bindings
        |
typed transport service skeletons
        |
application/business logic (not implemented yet)
        |
repository + unit-of-work ports
        |
SQLite adapter (Phase 2)
```

Generated files contain transport types only. Service skeletons validate basic
wire input and return clear gRPC statuses. They do not access domain models or
repositories, which prevents accidental Phase 2 implementation.

## Metadata flow

The client interceptor attaches `x-request-id` and an optional bearer token.
The server interceptor extracts them for the lifetime of each unary or streaming
handler through context-local variables. Logs include the request ID, RPC method,
and a token-present boolean; token values are never logged.

Request messages also contain `RequestContext`. Keeping a request ID in the
schema makes tracing explicit across queued or forwarded work later, while the
transport copy makes it available before message-specific business handling.

## Streaming and cancellation

The event subscription is a real server-streaming RPC. Phase 1 emits only typed
keepalive events so clients can verify that the connection remains active and
can be cancelled cleanly. This is a transport guarantee, not reliable message
delivery, presence publication, replay, or ordering.

File RPCs use streaming contracts to avoid requiring whole files in memory.
Actual storage, size/type validation, checksums, interruption cleanup, and
authorization remain Phase 3 work.

## Configuration and process lifecycle

Hosts, ports, worker count, deadlines, keepalive interval, and shutdown grace
come from validated environment settings. Both servers bind their configured
gRPC address, log identity, and stop gracefully on `Ctrl+C`. Tests bind ephemeral
ports to avoid machine-specific port conflicts.

## Future compatibility boundaries

- v1 client contracts do not depend on SQLite or Raft.
- `client_request_id` is present where later idempotency is required.
- LLM calls stay outside the chat process and future Raft state-machine apply.
- File contents use streams and remain separate from future replicated metadata.
- UTC protobuf timestamps avoid environment-local time ambiguity.

These seams do not claim any persistence, idempotency, authentication,
replication, consensus, failover, or recovery behavior today.

