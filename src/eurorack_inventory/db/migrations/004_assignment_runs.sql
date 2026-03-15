ALTER TABLE parts ADD COLUMN storage_class_override TEXT;

CREATE TABLE assignment_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    mode          TEXT NOT NULL,
    scope_json    TEXT NOT NULL DEFAULT '{}',
    plan_json     TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    undone_at     TEXT
);
