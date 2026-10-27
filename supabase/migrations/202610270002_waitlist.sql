-- Anonymous visitors submit through the API; browser roles cannot read or write this table.
BEGIN;
CREATE TABLE IF NOT EXISTS app_private.waitlist (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    interest TEXT NOT NULL DEFAULT 'full-product',
    source TEXT NOT NULL DEFAULT 'website',
    policy_version TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE app_private.waitlist ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app_private.waitlist FROM PUBLIC,anon,authenticated;
CREATE INDEX IF NOT EXISTS waitlist_created_at ON app_private.waitlist(created_at);
COMMIT;
