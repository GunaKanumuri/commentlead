BEGIN;
CREATE TABLE IF NOT EXISTS app_private.site_usage_daily (
    day TEXT NOT NULL,
    visitor_hash TEXT NOT NULL,
    page_views INTEGER NOT NULL DEFAULT 0 CHECK (page_views>=0),
    preview_attempts INTEGER NOT NULL DEFAULT 0 CHECK (preview_attempts>=0),
    previews_with_results INTEGER NOT NULL DEFAULT 0 CHECK (previews_with_results>=0),
    empty_previews INTEGER NOT NULL DEFAULT 0 CHECK (empty_previews>=0),
    preview_errors INTEGER NOT NULL DEFAULT 0 CHECK (preview_errors>=0),
    comments_returned INTEGER NOT NULL DEFAULT 0 CHECK (comments_returned>=0),
    PRIMARY KEY(day,visitor_hash)
);
ALTER TABLE app_private.site_usage_daily ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app_private.site_usage_daily FROM PUBLIC,anon,authenticated;
COMMIT;
