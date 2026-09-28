CREATE TABLE channel_join_requests (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(channel_id, user_id)
);

CREATE INDEX channel_join_requests_owner_idx
ON channel_join_requests(channel_id, status, created_at);
