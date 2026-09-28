# Post-Phase-4 enhancement: presence in the Tkinter GUI

Status: implemented; all 60 automated tests passed. This is a client display enhancement after Milestone 1,
not a Raft phase.

## Scope and assumptions

The left Registered users list shows an `online`, `offline`, or `unknown` label
beside each username. When a member selects a channel, its roster on the right
shows the same labels and a header such as `Channel members (2 online)`.
Statuses come from the existing authenticated `PresenceService.GetPresence`
RPC. `unknown` means a request failed or has not completed; it is not counted
as online and is shown separately in the header (for example,
`Channel members (1 online, 1 unknown)`). A channel's roster remains visible
only to its members. No new
dependency, configuration value, server contract, or external action is needed.

## What changed and how it works

After login the GUI sends the existing heartbeat for its own session, then
refreshes presence for listed users and visible channel members about every
five seconds. Those gRPC requests run in a small background thread pool, so
presence lookup does not block the Tkinter event loop. The results are placed
in a queue and applied on the UI thread. The left list preserves the currently
selected user and scroll position when status text changes. The right roster
re-renders its labels and counts only members whose latest known status is
`online`. The existing five-second channel/member refresh also detects new
users and membership changes; the next presence refresh picks up their status.

The backend already defines online as having a recent session heartbeat and
offline as no heartbeat within `PRESENCE_TIMEOUT_SECONDS`. Closing a client
does not make it offline immediately: the server marks it offline after that
timeout. If the chat server is unreachable, the GUI shows `unknown` rather than
claiming the user is offline.

## Architecture and distributed-systems note

Presence remains transient state in the single chat-server process. It is not
written to SQLite or the future Raft log, and the online count is only a view
of the latest server-reported status. The GUI's five-second refresh introduces
bounded display lag; it does not promise instantaneous presence. Up to eight
per-user GetPresence requests run concurrently in one refresh, and a slow
refresh is not duplicated while it is still in progress. No consensus or
cross-server presence aggregation was added.

## Files changed

- `client/api.py`: typed `get_presence(user_id)` call using the existing RPC.
- `client/gui.py`: background polling, cached status labels, roster count,
  and UI-thread updates.
- `tests/test_gui_presence.py`: headless label/count/selection and client RPC
  tests.
- `tests/test_phase3_collaboration.py`: server snapshot online/timeout test.
- `tests/test_grpc_skeleton.py`: bounded Windows cleanup retry for cancelled
  stream handlers finishing a final database read before temporary-file removal.
- `README.md` and `docs/architecture.md`: evaluator behavior and limits.

## Expected output and verification

From the repository root:

```powershell
.venv\Scripts\python -m compileall -q client tests
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
.\scripts\start_client.cmd --gui
```

Open two GUI clients and log in as two users. Both names should show `online`
in the left list after the initial refresh. If both are members of a selected
channel, the right header should show `2 online`. Close one client and wait for
the configured heartbeat timeout plus a refresh interval; the other should see
the closed user as `offline` and the count drop to `1 online`. Stop the chat
server to see `unknown` instead of a misleading offline status. Automated
checks exercise the rendering helpers and the GetPresence RPC. Compilation,
all 60 tests, and `pip check` passed. A live Tkinter layout check is still a
manual verification step.

## Limitations and out of scope

The client currently polls one GetPresence RPC per visible user, with at most
eight in parallel; this is suitable for the course demo, not a very large user
directory. Presence is process-local and resets on server restart. No new
protobuf batch endpoint, push-presence UI stream, cross-server aggregation, or
Raft behavior was introduced.
