# Post-Phase-4 enhancement: delete channels and view members

Status: implemented; 52 automated tests passed. This is a requested Milestone 1
enhancement, not a Raft phase.

## Scope and assumptions

The owner of a channel can permanently delete it. Deletion removes the channel,
all memberships and pending join requests, message history, and file metadata.
Members can view a channel roster; nonmembers cannot. Only the owner sees a
Remove button beside other members. The owner cannot remove themself. The user
approved deletion of history and file records. Uploaded file *bytes* remain on
local disk as unreferenced data, because physical-byte erasure was not requested
and is not transactional with SQLite. They are no longer downloadable through
the application. No new software or configuration is required.

## What changed and how it works

The versioned `ChannelService` contract now has `DeleteChannel`. Its handler
validates the request ID and channel ID, authenticates the caller, and asks the
channel application to enforce ownership. A `DeleteChannelCommand` records the
durable operation's inputs. The repository deletes one channel row inside an
immediate SQLite transaction. Existing foreign keys cascade the deletion to
members, join requests, messages, and file records. Other channels and user
accounts remain unchanged. A repeated delete after success returns `NOT_FOUND`;
it does not recreate anything.

`ListMembers` now allows any current member, not only the owner. The Tkinter
client shows the selected channel's roster in a panel to the right of chat.
It adds Remove buttons only for the owner and only beside other members. The
owner also gets a Delete channel button with a confirmation explaining exactly
what is removed. The GUI refreshes the roster and channel list after changes
and during its existing five-second poll, so other clients see changes shortly.

An already-open chat event stream now checks authorization before each event
or idle keepalive. A removed member or deleted channel loses that stream rather
than continuing to receive live events. File upload also rechecks the channel
under its final database transaction, because a channel could be deleted while
chunks are arriving; a failed late upload cleans up its newly written file.

## Distributed-systems and design notes

The operation is atomic only for SQLite rows on this single server. The delete
command is shaped for later routing through Raft, but no replication, majority
commit, or distributed deletion is claimed. Filesystem bytes are outside the
database transaction, so they are intentionally not erased by this operation.
Retries after a lost delete response are ambiguous: the second call returns
`NOT_FOUND`. A future phase could add a durable tombstone/idempotency result if
needed for replicated retries. Live streams are process-local and may close
after the next event/keepalive rather than at the exact deletion instant.

## Important files

- `proto/chat/v1/channel.proto` and generated bindings: added the typed
  deletion RPC, reusing the existing channel-ID request shape.
- `server/application/commands.py`, `server/application/channels.py`,
  `server/repositories/sqlite.py`, and `server/services.py`: command, owner
  check, transactional delete, roster authorization, and RPC mapping.
- `server/application/files.py`: final authorization check for an upload that
  overlaps deletion.
- `client/api.py` and `client/gui.py`: member list, owner-only Remove controls,
  confirmation, deletion, and refreshed display.
- `tests/test_phase2_access.py` and `tests/test_phase3_collaboration.py`:
  roster permission, delete cascade, restart, and stream-revocation tests.
- `README.md`, `docs/api_contracts.md`, `docs/architecture.md`, and
  `docs/requirements.md`: current behavior and limits.

## Expected behavior and verification

From the repository root, run:

```powershell
.venv\Scripts\python scripts\generate_stubs.py
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
.\scripts\start_milestone1.cmd
```

Then open a second client with `scripts\start_client.cmd --gui`. Register or
log in as two users. Have one create a channel and approve the other's join
request. Select the channel in each window: both should see the roster on the
right; only the owner should see Remove buttons and Delete channel. Removing
the other member should clear their chat view within the next refresh. Add the
member back, send a message, and upload a file. Then delete the channel as the
owner and confirm it disappears in both windows. Neither history nor the file
should be retrievable through the app.

Automated verification: binding generation, compilation, all 52 unit and
integration tests, and dependency check passed. Tests use temporary databases,
so no real channel in the user's database was deleted. The GUI appearance and
button clicks were not manually verified in this run.

## Limitations and out of scope

No physical wipe of uploaded bytes, channel recovery/undo, push notification
of roster changes, durable deletion receipt for retries, or Raft integration
was added. Do not use the current plaintext gRPC server as a public-internet
service without additional transport security and hardening.
