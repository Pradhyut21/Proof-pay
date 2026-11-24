CREATE TABLE IF NOT EXISTS human_attempts (
    task_fingerprint TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    submitted_answer TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_fingerprint, idempotency_key)
);
