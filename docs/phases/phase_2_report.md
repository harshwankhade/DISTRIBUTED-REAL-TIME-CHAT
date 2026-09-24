# Phase 2 - Users, Sessions, Channels, and Administration

**Status:** Complete

## Scope completed

Phase 2 implemented the access-control foundation on one chat server. Users and
password hashes are persisted in SQLite, login returns expiring opaque session
tokens, logout revokes sessions, and every protected Phase 2 operation checks
the current account. Channel membership and administrator operations are also
persistent and transactional.

Messaging, live presence, file storage, LLM behavior, and Raft were not added.

## Assumptions

- Every active, non-archived channel is currently discoverable and self-joinable
  by active users. Private or invite-only channels were not requested.
- Administrators do not automatically receive permission to read future channel
  messages; they only receive the management permissions implemented here.
- One chat server owns one SQLite database during Milestone 1.
- Local development still uses plaintext gRPC. Deployment TLS is future work.
- Usernames are case-insensitively unique and contain 3-64 safe characters.
- Passwords must contain at least 12 characters.

## What was implemented

- Ordered, repeatable SQLite migration infrastructure and initial schema.
- SQLite repositories for users, sessions, channels, and memberships.
- A unit-of-work transaction boundary with commit/rollback behavior.
- Salted `scrypt` password hashing and constant-time digest comparison.
- Random opaque session tokens stored only as SHA-256 hashes.
- Login, expiry checking, logout, disabled-user checks, and session revocation.
- Admin-only user creation, enable/disable, role changes, channel creation,
  archive, and membership management.
- Authenticated channel list/join/leave operations and pagination tokens.
- Authentication guards on future chat, presence, and file skeleton RPCs.
- Repeatable migration and seed commands with no committed passwords.
- Repository, security, application, gRPC, restart, and acceptance tests.

## Distributed-systems concepts involved

### Durable state and restart recovery

Users, session state, channels, archive state, and memberships live in SQLite
rather than process memory. Tests stop the gRPC server, create another server
against the same database, and verify that membership and archive state remain.
This is local crash/restart persistence, not distributed replication.

### Transactions

Each application operation uses one unit of work. Related changes—such as
disabling a user and revoking all sessions—commit atomically or roll back. This
prevents partially applied local state.

### Authentication versus authorization

Authentication determines which active user owns a valid session. Authorization
then checks role or membership. The difference is visible in gRPC statuses:
invalid/expired/revoked sessions return `UNAUTHENTICATED`, while an authenticated
normal user calling an admin RPC returns `PERMISSION_DENIED`.

### Future deterministic command boundary

Durable write inputs are immutable commands with IDs and timestamps chosen
before repository application. That boundary can later be placed behind Raft,
but Phase 2 executes commands only in local SQLite transactions. No consensus or
replication guarantee is claimed.

## Architecture and design decisions

- Python's standard-library `hashlib.scrypt` avoids an unnecessary password
  dependency while providing a memory-hard password hash with random salts.
- Raw login tokens are never stored. Hashing them limits damage if the session
  table is exposed.
- Separate connections per unit of work avoid sharing a SQLite connection
  unsafely across gRPC worker threads.
- Migrations run automatically when the chat server starts and are also exposed
  through an explicit command.
- Disabling a user revokes all existing sessions in the same transaction.
- Admins can list archived channels; normal users see active channels only.
- Archived channels reject joins and all membership changes.
- Existing v1 protobuf field numbers and RPCs were preserved.

## Files created or modified

Every Phase 2 file change is listed below.

```text
.env.example
.env (local, Git-ignored configuration copy)
README.md
requirements.txt

client/grpc_client.py
client/main.py

common/config.py

docs/api_contracts.md
docs/architecture.md
docs/requirements.md
docs/phases/phase_2_report.md

scripts/migrate.cmd
scripts/seed_data.cmd

server/application/__init__.py
server/application/admin.py
server/application/auth.py
server/application/channels.py
server/application/commands.py
server/database.py
server/grpc_server.py
server/main.py
server/migrate.py
server/migrations/001_initial.sql
server/repositories/__init__.py
server/repositories/sqlite.py
server/security/__init__.py
server/security/passwords.py
server/security/tokens.py
server/seed.py
server/services.py
server/validation.py

tests/test_auth_application.py
tests/test_config.py
tests/test_grpc_skeleton.py
tests/test_phase2_access.py
tests/test_placeholders.py
tests/test_repositories.py
tests/test_security.py
```

The protobuf sources and generated bindings were not changed. Phase 1 contracts
already contained the fields and RPCs needed for Phase 2.

## How the code works

The chat server applies migrations, creates a unit-of-work factory, and wires
authentication, channel, and admin application services into the existing gRPC
handlers. Login verifies the password hash, creates a session, stores the token
hash, and returns the raw token once. Protected RPCs receive that token from the
metadata interceptor and validate it before executing their operation.

Repository writes occur inside an explicit transaction. gRPC handlers translate
safe `ApplicationError` codes into matching gRPC statuses and never return
database details or secrets.

## Configuration and external prerequisites

Configuration maintenance update (September 24, 2026): `python-dotenv` was
added as a pinned dependency so local commands automatically read the
repository-root `.env` file. Existing process environment values take
precedence. SQLite, `scrypt`, secure random generation, and hashing still come
from the Python standard library.

`CHAT_DATABASE_PATH` selects the local database and `SESSION_TTL_SECONDS`
controls token lifetime. Copy `.env.example` to the Git-ignored `.env` file and
fill local values there. Seed passwords can be supplied through
`SEED_ADMIN_PASSWORD` and `SEED_SAMPLE_PASSWORD` in `.env`; blank or absent
values retain the hidden interactive prompts. Real process variables override
the file, which is useful for deployment and temporary overrides.

## Expected output and behavior

- `migrate.cmd` reports `001_initial.sql` the first time and no new migration on
  later runs.
- `seed_data.cmd` creates `admin`, `alice`, and `bob` once, then reports them as
  existing on repeated runs.
- Correct credentials return a token and expiry timestamp.
- Wrong credentials or invalid/expired/revoked tokens return `UNAUTHENTICATED`.
- Disabled accounts cannot log in; their existing sessions are revoked.
- Normal users receive `PERMISSION_DENIED` from admin RPCs.
- Membership and archive rules remain true after server restart.

## Tests performed

The final automated commands were run on September 24, 2026:

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
```

All 29 automated tests passed. Coverage includes:

- automatic repository-root `.env` loading and process-environment precedence;

- salted password hashing, verification, minimum length, and token hashing;
- repeatable migrations and repository persistence after reopening SQLite;
- successful login, admin user creation, channel creation, self-join, admin
  member management, listing, logout, and subsequent token rejection;
- invalid token, expired token, disabled user, disabled-user protected request,
  non-member access, and forbidden normal-user admin calls;
- archived-channel behavior and membership/archive persistence after restart;
- retained Phase 0/1 configuration, models, contract, health, LLM skeleton,
  streaming, cancellation, and process-startup tests.

Dependency validation reported no broken requirements, and all three one-shot
process launchers exited successfully on isolated ports.

Manual process verification used an isolated database and ephemeral port. The
migration ran, seeding succeeded, repeated seeding created no duplicates, and
the client smoke check reported health serving, login `OK`, a keepalive event,
and successful cancellation.

## Exact verification steps for the user

From the repository root:

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\scripts\migrate.cmd
.\scripts\seed_data.cmd
.venv\Scripts\python -m unittest discover -s tests -v
```

Before seeding, edit `.env` and provide passwords of at least 12 characters.

Start the chat server in one terminal:

```powershell
.\scripts\start_chat.cmd
```

In another terminal, use the same seeded sample password:

```powershell
.\scripts\start_client.cmd --smoke
```

Set `SMOKE_USERNAME` and `SMOKE_PASSWORD` in `.env`; for `alice`, the smoke
password should match `SEED_SAMPLE_PASSWORD`.

The full admin, disabled-user, membership, archive, restart, and expiry
acceptance scenarios are reproducible with:

```powershell
.venv\Scripts\python -m unittest tests.test_phase2_access tests.test_auth_application -v
```

## Known limitations, placeholders, mocks, and TODOs

- There is no password change/reset or token refresh flow.
- No login rate limiting or account lockout policy exists yet.
- gRPC transport is plaintext for local development.
- Page tokens encode a local numeric offset; they are not stable under concurrent
  list mutations.
- Audit events are not yet persisted.
- Channels have no private/invite-only visibility mode.
- Chat, presence, and file RPCs authenticate but still return `UNIMPLEMENTED`.
- LLM RPCs remain an independent Phase 1 skeleton.
- Retry deduplication is not implemented.

## Explicitly out-of-scope functionality not implemented

Messages, history, server-pushed message/presence events, presence heartbeats,
file upload/download storage, checksums, LLM inference/context filtering,
idempotency, retry recovery, Raft logs, leader election, replication, majority
commit, failover, and multi-node recovery were not implemented.
