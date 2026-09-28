# Post-Phase-4 enhancement: registration and channel owners

Status: implemented and automated tests passed. This is an approved change to
Milestone 1 permissions, not a new Raft phase.

## Scope and assumptions

The separate administrator is retired. Any registered user can create a
channel and becomes its owner and first member. A nonmember may discover a
channel and request access; only its owner can approve or reject that request,
or add/remove members directly. The user approved discarding the former
admin-owned channel's messages and file metadata. Ordinary-user accounts are
preserved. No Raft, cross-server notifications, or new LLM behavior was added.

## What changed and how it works

`AuthService.Register` creates a normal account with a salted password hash and
an expiring session. `ListUsers` shows active registered users to signed-in
clients. Login now returns the user ID and username for the GUI. Legacy admin
tokens are denied and the old `AdminService` is no longer registered.

`ChannelService.CreateChannel` uses the existing `created_by` field as owner and
adds the creator as a member in one transaction. `JoinChannel` now stores a
pending request instead of granting membership. Repeated requests share one
pending row. Only the owner can list and decide requests, list members, or
directly add/remove members. Approval and membership insertion happen in the
same SQLite transaction. The owner cannot remove themself or leave the channel.
Membership checks still protect history, live chat, files, and AI context.

The Tkinter login screen has Register and Log in. The left side shows registered
users, a separator, and discoverable channels. A nonmember can request to join;
the owner receives a Yes/No pop-up while their GUI is open. The GUI checks for
pending requests every five seconds. This is polling, not a guaranteed
notification service; pending requests survive a client/server restart.

## Design and distributed-systems concepts

SQLite remains the single-server source of truth. Join decisions and member
changes use transactions so an approval cannot be saved without its membership
change. Pending-request uniqueness handles concurrent duplicate join attempts.
Channel ownership is scoped to one channel; it is not a global role. These
durable decisions will need deterministic command routing when Raft is later
integrated; no replication or consensus is claimed here. The v1 protobuf
contracts gained additive fields and RPCs; old Admin RPC bindings remain only
for compatibility and return `UNIMPLEMENTED` from the chat server.

## Important files

- `proto/chat/v1/{auth,channel,common}.proto` and generated Python bindings:
  registration, user listing, join decisions, member management, and owner and
  membership fields.
- `server/application/{auth,channels}.py`, `server/services.py`, and
  `server/grpc_server.py`: access rules and gRPC handlers.
- `server/repositories/sqlite.py` and `server/migrations/003_join_requests.sql`:
  durable requests and transactional repository operations.
- `client/{api,gui}.py`: new RPC calls and desktop interactions.
- `server/retire_legacy_admin.py` and `scripts/retire_legacy_admin.cmd`:
  one-time backup and removal of the retired account and its owned channels.
- `scripts/start_milestone1.ps1`, `scripts/seed_data.cmd`, `server/seed.py`,
  `.env.example`, `README.md`, and architecture/API/requirements notes:
  updated launch and evaluator guidance. The seed command is retired.
- `tests/test_phase2_access.py`, `tests/test_retire_legacy_admin.py`, and the
  adjusted Phase 3/4 fixtures: new permission and regression checks.

## Configuration, expected behavior, and verification

No new dependency, secret, or external account is needed. Existing `.env`
address, database, and LLM settings still apply. Stop the old services first.
`start_milestone1.cmd` migrates the database, makes a timestamped SQLite backup
if a legacy admin exists, then deletes the old admin-owned channels and their
message/file metadata. Old uploaded bytes remain on disk but are not listed or
downloadable. Ordinary users can log in with existing passwords. A fresh
evaluator can register new users without seeding.

Run from the repository root:

```powershell
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
.\scripts\start_milestone1.cmd
.\scripts\start_client.cmd --gui
```

In the first GUI, register Alice and create a channel. In the second, register
Bob, select the channel, and request to join. Alice should see a permission
prompt within five seconds. Before approval Bob cannot see history or send;
after approval he can. Alice can select Bob in Registered users and remove him.
Close and restart the chat server to verify the membership decision persists.

Automated checks cover registration, duplicate/invalid credentials and tokens,
owner-only decisions, nonmember access, duplicate and concurrent requests,
restart persistence, old-admin RPC retirement, and a recoverable legacy-data
backup. The complete suite also exercises prior messaging, files, presence,
and LLM privacy behavior.

## Limitations and out of scope

The GUI owner must be online to see the prompt, though pending requests persist.
There is no push notification for approvals, no self-service password reset,
and no public global user disable or channel archive action. Existing
`seed_users` remains as a legacy test fixture helper, but its CLI and normal
startup no longer create an admin. The GUI has not been manually exercised by
automated tests. There is no Raft, multi-server state sharing, or replicated
join-request guarantee yet.
