# Distributed Real-Time Chat and Collaboration Tool — Demo 1 Project Report

**Milestone:** 1 (Phases 0–4, plus approved usability changes)  
**Report date:** 30 September 2026  
**Implementation:** Python desktop clients, one chat application server, one separate LLM server

> **Evidence note:** The automated results in Section 10 were run for this report. Genuine GUI screenshots could not be captured in this environment, so the four clearly marked screenshot positions are **pending**, not fabricated images. Add screenshots from a running demo before submitting a final illustrated copy.

## 2. Introduction

This project is a real-time group chat and collaboration application. People can register, log in, create or join channels, exchange messages, see who is online, and share files. The desktop interface also offers three AI tools: a draft smart reply, a conversation summary, and suggested next steps.

The client and chat server communicate using **gRPC**, with Protocol Buffers defining typed requests and responses. gRPC supports the long-lived server stream used to deliver new chat events without repeatedly requesting the entire history. A separate LLM server keeps model inference away from the chat database and normal messaging path. The chat server checks access and prepares a small, authorized conversation context before asking the LLM server for a response.

**Demo 1 / Milestone 1 scope** is a working single-chat-server collaboration system, with the LLM running as a second service. It demonstrates service separation and partial-failure handling, but **does not** include Raft, replicated chat servers, or automatic failover. Those belong to Milestone 2.

## 3. Problem Statement

A useful communication platform must do more than pass text between two windows. A group needs shared channels for topic-focused discussion, reliable access to earlier messages, file exchange, and an indication of who is currently available. It also needs rules for who may enter a channel and who may manage its membership. As discussions grow, finding decisions and deciding what to do next become harder; intelligent assistance can help summarize context and draft a response.

These needs introduce security and system-design problems. A user must not read another channel's messages or files. An AI component must not bypass those permissions merely because it can generate text. A temporarily unavailable AI service must not stop ordinary chat. Demo 1 addresses these requirements on one chat server and makes the remaining distributed-consensus work explicit.

## 4. Objectives

1. Build typed client–server communication with gRPC and Protocol Buffers, including live server-streamed events.
2. Support multiple registered users, persistent channels, membership decisions, messages, history, files, and presence.
3. Run a separate gRPC LLM service that supplies smart replies, summaries, and context-aware suggestions using only authorized context.
4. Keep durable writes behind application commands and repositories so future Raft integration has a clear boundary, without claiming replication exists now.

## 5. System Architecture

```text
 Tkinter client A     Tkinter client B     Tkinter client C
 (register/chat)      (chat/files)       (chat/presence)
        \                  |                  /
         \------- gRPC + bearer token ------/
                         |
                         v
              Chat application server
         Auth | Channels | Chat | Presence
              Files | AI gateway
                |                |
       repository interface      | gRPC + deadline
                |                v
                v          Separate LLM server
          SQLite database     Qwen adapter or
          + local file store  deterministic mock
```

| Component | Responsibility |
|---|---|
| Tkinter clients | Present registration, channels, chat, files, owner controls, presence, and AI actions. Each uses typed gRPC calls; background work keeps the interface responsive. |
| Chat application server | Authenticates sessions, enforces channel membership and owner permissions, stores durable state, publishes live events, and constructs authorized AI context. |
| SQLite and local file store | SQLite holds users, sessions, channels, memberships, join requests, messages, and file metadata. Uploaded bytes are kept separately on local disk. |
| Separate LLM server | Performs inference only. It has no chat-database access and does not authenticate end users or modify chat state. |

These are **logical service roles**, not a five-node Raft cluster. The current chat server has one local database. New-message and presence streams are process-local; a lost live event can be recovered from durable message history, but there is no cross-server event fan-out.

## 6. Functionalities Implemented

### Authentication and sessions

The GUI offers **Register** and **Log in**. Passwords are stored as salted `scrypt` hashes, not plaintext. A successful registration or login creates an opaque, expiring session token; logout revokes it. Protected RPCs reject missing or invalid tokens. The application also rejects requests from an account marked disabled in the database, although **there is no current user-facing global-admin control to disable accounts**.

### Channels, administration, and messaging

Any registered user can create a channel and becomes its **owner** and first member. The left panel shows registered users and discoverable channels. A nonmember may request to join; the owner can approve or reject the persisted request. The owner's GUI checks pending requests periodically and displays a Yes/No prompt. The owner may also select a user, choose one of their owned channels from a dropdown, and add that user directly. Members can see the selected channel's roster; only the owner sees removal controls for other members and can permanently delete the channel.

Members can send messages and read paginated history. New messages appear through a live server stream, with usernames rather than internal user IDs shown in the GUI. A `client_request_id` prevents duplicate message creation when the same request is retried. Channel deletion removes its memberships, pending requests, message history, and file **records** in a SQLite transaction. It does **not** physically erase already uploaded file bytes from disk.

The older `AdminService` protobuf still exists for compatibility, but it is **not registered** on the chat server. Its calls return `UNIMPLEMENTED`. There is no separate administrator account, global user-management UI, or cross-channel override in the current application. Here, “administrator operations” means **owner-only management of a particular channel**.

### File sharing and presence

Members can upload allowed file types in chunks and download them in chunks. The server checks membership, filename, MIME type, configured size limit, and SHA-256 checksum. A valid attachment appears in the chat timeline with a **Download** button. Downloads verify the checksum. Nonmembers cannot list or download a channel's files; interrupted or invalid uploads remove partial temporary files.

The client sends heartbeats while signed in. The server considers a user online while at least one of that user's sessions has a recent heartbeat; after the configured timeout, the user becomes offline. The GUI shows online/offline/unknown beside registered users on the left and channel members on the right, plus an online count for the selected channel. These labels refresh periodically rather than instantaneously. “Unknown” means the status request failed or has not completed; it is not treated as offline.

### AI assistance

**Smart reply** drafts a short response and places it in the message-entry box for the user to review; it is not sent automatically. **24h summary** summarizes the selected channel's last 24 hours in the GUI, while the RPC supports an explicit UTC time range. **Next steps** proposes action items grounded in the selected conversation. The output is advisory and is not saved as a message unless the user sends it.

## 7. gRPC Communication

The versioned contracts live in `proto/chat/v1/` under protobuf package `distributed_chat.v1`. The most important currently active RPCs are:

| Service | Principal RPCs | Use |
|---|---|---|
| `AuthService` | `Register`, `Login`, `Logout`, `ListUsers` | Accounts and sessions |
| `ChannelService` | `CreateChannel`, `ListChannels`, `JoinChannel`, `ListJoinRequests`, `DecideJoinRequest`, `ManageMember`, `ListMembers`, `LeaveChannel`, `DeleteChannel` | Channel discovery and owner-managed membership |
| `ChatService` | `SendMessage`, `GetHistory`, `SubscribeEvents` | Durable messages, pagination, live message/file events |
| `PresenceService` | `Heartbeat`, `GetPresence`, `SubscribePresence` | Heartbeats, status snapshots, transition stream |
| `FileService` | `UploadFile`, `DownloadFile`, `ListChannelFiles` | Chunked transfer and attachment discovery |
| `LLMService` | `GetSmartReply`, `SummarizeConversation`, `GetSuggestion` | Authenticated AI gateway on chat server; inference on separate LLM server |
| `HealthService` | `Check` | Health and service identity |

`AdminService` is a **retired contract**, not an available service. `JoinChannel` creates a **pending join request**; it does not immediately grant membership.

For a normal message, the Tkinter client sends a `SendMessage` request with its session token and request ID. The chat server authenticates the session, checks membership, writes the message to SQLite, then publishes a new-message event to current `SubscribeEvents` subscribers. Each subscriber has a long-lived **server-streaming** RPC; cancellation closes it. `GetHistory` is the recovery and pagination path if a client was disconnected or missed a live event. `UploadFile` is client streaming; `DownloadFile` is server streaming.

The client supplies an `authorization: Bearer <token>` metadata value on protected calls. `x-request-id` supports correlation across logs and service calls. State-changing message and upload requests also carry `client_request_id` for deduplication. Invalid input, unauthenticated requests, and forbidden access are mapped to appropriate gRPC status codes rather than returned as successful chat operations.

For AI calls, the client addresses `LLMService` on the **chat-server endpoint**. The chat server discards any caller-provided identity or conversation context, checks the token and channel membership, loads its own bounded context, then calls the **separate LLM server over gRPC with a deadline**. The LLM server receives only this filtered input.

## 8. LLM Integration

The project supports two interchangeable adapters behind the LLM server's gRPC service:

- **Local model:** Qwen2.5-3B-Instruct, Q4_K_M GGUF, run through `llama-cpp-python`. The model file is local; there is no cloud API key. The default CPU-first configuration uses zero GPU layers. The model file was found in this workspace, but this report's automated tests do not benchmark its output quality or speed.
- **Deterministic mock:** Produces predictable text for repeatable integration tests and a quick demo. It is explicitly a mock, not an intelligent model. The built-in default is `LLM_ADAPTER=mock`; `LLM_ADAPTER=local` selects Qwen when the optional runtime and model are installed.

The context builder first authenticates the requester and verifies membership in the selected channel. It then reads only that channel's recent messages, optionally within the summary's time range. Configurable message-count and character limits bound what leaves the chat server. Caller-supplied `requester_id` and `authorized_context` are ignored at the public gateway. The local-model adapter uses task-specific instructions for replies, summaries, or grounded next steps.

If the LLM process is stopped, fails, or exceeds the configured deadline, the gateway returns a **clearly labelled fallback answer**. Users can still log in, send messages, read history, and transfer files; AI availability is not a prerequisite for ordinary chat. The fallback is not presented as a real generated answer.

## 9. Implementation Details

**Technologies.** Python 3.11+, Tkinter, `grpcio`, `grpcio-tools`, Protocol Buffers, SQLite, `python-dotenv`, and optionally `llama-cpp-python` for local Qwen inference. The base dependencies are pinned in `requirements.txt`; the optional local-model dependency is in `requirements-llm.txt`.

**Key project folders and files:**

```text
client/                  Tkinter UI and typed gRPC client calls
common/                  configuration, metadata, errors, structured logging
domain/                  domain models
proto/chat/v1/           versioned .proto contracts and generated bindings
server/application/      auth, channels, chat, files, presence, AI orchestration
server/repositories/     repository interfaces and SQLite implementation
server/migrations/       ordered SQL schema changes
llm_server/              gRPC inference service and model adapters
tests/                   unit, repository, gRPC, concurrency, and failure tests
scripts/                 setup, migration, launch, stop, and stub generation
docs/                    architecture, API, phase notes, and this report
```

Important entry points are `client/gui.py` (desktop interface), `client/api.py` (GUI-facing RPC client), `server/grpc_server.py` and `server/services.py` (chat transport), `server/application/` (rules and commands), `server/repositories/sqlite.py` (SQL persistence), `llm_server/adapters.py` (mock/Qwen adapters), `llm_server/grpc_server.py` (LLM transport), and `scripts/start_milestone1.cmd` (demo launcher).

**Database tables.** `users` and `sessions` store account and session state. `channels`, `channel_members`, and `channel_join_requests` store ownership-related channel state and join decisions. `messages` stores message history and message deduplication keys. `files` stores attachment metadata, checksums, storage references, and upload deduplication keys—not the file bytes. `schema_migrations` records applied migrations. Presence heartbeats and live subscriptions are **in memory**, not SQLite tables.

**Configuration.** The application has validated defaults in `common/config.py` and runs without `.env`. Create a local `.env` only to override addresses, paths, limits, or the LLM adapter; for Qwen, set `LLM_ADAPTER=local` and the local `LLM_MODEL_PATH`. Process environment variables override `.env`. The `.env` file is local and should not be committed; ports, credentials, model path, file limits, and timeouts are not embedded in business logic. The local model file and uploaded data are also excluded from normal source control. New users register in the GUI; no seeded administrator credentials are needed.

To start from the repository root after the documented setup, run:

```powershell
.\scripts\start_milestone1.cmd
.\scripts\start_client.cmd --gui     # another client window
.\scripts\stop_milestone1.cmd       # stop background services
```

The first command migrates the local database, starts chat and LLM as separate processes, and opens a GUI client. The launch steps and prerequisites are described in `README.md`.

## 10. Testing and Results

**Automated checks run on 30 September 2026:**

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m compileall -q common domain proto server llm_server client tests scripts
.venv\Scripts\python -m pip check
```

The complete test suite finished **60 tests, OK**. Compilation exited successfully, and `pip check` reported **“No broken requirements found.”** The suite uses temporary databases and ephemeral gRPC ports; it does not alter the user's live chat data. The following table identifies representative verified behavior rather than claiming a separate manual GUI test for every row.

| Requirement | Automated evidence and observed result |
|---|---|
| Login and invalid credentials | Login tests reject an unknown account with `UNAUTHENTICATED` and an empty username with `INVALID_ARGUMENT`. Registration, logout, token expiry, duplicate registration, and disabled-account checks also pass. |
| Multi-user messaging | Three concurrent clients send messages. Retrying the same request yields the original message IDs; paginated history contains exactly the three unique messages. A stream receives a new message, while a nonmember cannot read history. |
| Presence | Heartbeat/status tests observe online, then offline after the configured timeout; the presence stream reports transitions. GUI rendering tests verify status labels and the member online count. |
| File upload/download | Chunked upload and download yield matching bytes and SHA-256. Repeat upload returns the same file ID. Nonmember download/listing is denied; bad checksum and incomplete uploads leave no partial stored file. |
| Channel administration | Tests show only the channel owner can decide joins, remove another member, or delete a channel. Members can view the roster; outsiders cannot. The retired global `AdminService` returns `UNIMPLEMENTED`. |
| LLM features and privacy | Mock-backed gRPC tests cover a smart reply, time-range summary, bounded context, and forbidden nonmember suggestion. Forged caller context and messages from another channel do not reach the model adapter. |
| LLM server failure | Stopping the LLM server returns a labelled fallback; a subsequent chat message still succeeds. A slow adapter also triggers the deadline fallback. |

**Manual Demo 1 verification sequence (expected, not run for this report):** register Alice, Bob, and Charlie in separate GUI windows; have Alice create a channel and approve the others; exchange messages; upload a small allowed file and download it using the in-chat button; observe presence after closing one client; use the three AI buttons; stop only the LLM server and confirm a fallback while sending another message. The GUI's visual layout and real Qwen response were **not manually retested** for this report.


## 11. Limitations and Future Work

Demo 1 runs **one chat application server** with one local SQLite database. There is **no Raft log, majority commit, replicated message order, leader election, automatic failover, or restarted-node catch-up**. If the chat server stops, chat is unavailable until it is restarted. Live streams and presence are process-local. Uploaded file bytes are local to the chat server, and deleting a channel removes file metadata but leaves unreferenced bytes on disk. gRPC currently uses plaintext local connections; a public deployment would need transport security and operational hardening.

The next milestone is to implement a standalone real Raft engine, then route durable chat writes through it. That work should add leader election, ordered log replication, majority-based commit, retry-safe application of commands, leader-failure handling, and follower recovery. Presence heartbeats, live connections, LLM prompts/results, and uploaded file bytes should **not** be described as Raft-replicated just because durable metadata may later be replicated. Multi-machine deployment will also require an explicit secure network and file-storage strategy.

## 12. Conclusion

Demo 1 delivers a runnable, multi-user chat application with registration, owner-managed channels, live and historical messages, authorized file transfer, presence display, and three AI-assistance actions. The AI service runs separately over gRPC, receives bounded authorized context, and can fail without stopping normal chat. The tested command and repository boundaries provide a starting point for Milestone 2, while the present system remains honest about its single-server limits: **Raft replication and failover are future work, not current guarantees.**
