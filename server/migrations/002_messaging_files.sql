CREATE TABLE messages (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    sender_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    UNIQUE(sender_id, client_request_id)
);

CREATE INDEX messages_channel_sequence_idx
ON messages(channel_id, sequence DESC);

CREATE TABLE files (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    uploader_id TEXT NOT NULL REFERENCES users(id),
    original_name TEXT NOT NULL,
    storage_reference TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    checksum_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    UNIQUE(uploader_id, client_request_id)
);

CREATE INDEX files_channel_id_idx ON files(channel_id);
CREATE INDEX files_message_id_idx ON files(message_id);
