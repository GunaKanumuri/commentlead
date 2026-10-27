"""Test Database: focused API/service functions."""
from backend import runtime as core

def init_db():
    if core.database.is_postgres():
        core.database.verify_schema()
        return
    conn = core.get_db()
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.executescript("\n    CREATE TABLE IF NOT EXISTS users (\n        id INTEGER PRIMARY KEY,\n        email TEXT UNIQUE COLLATE NOCASE,\n        password_hash TEXT,\n        created_at TEXT,\n        plan TEXT DEFAULT 'free'\n    );\n    CREATE TABLE IF NOT EXISTS workspaces (\n        id INTEGER PRIMARY KEY,\n        user_id INTEGER DEFAULT 1,\n        name TEXT,\n        pitch TEXT,\n        signals TEXT,\n        rules TEXT,\n        blocklist TEXT DEFAULT ''\n    );\n    CREATE TABLE IF NOT EXISTS leads (\n        id INTEGER PRIMARY KEY,\n        workspace_id INTEGER,\n        comment_id TEXT,\n        video_id TEXT,\n        video_title TEXT,\n        author TEXT,\n        text TEXT,\n        score INTEGER DEFAULT 0,\n        reason TEXT DEFAULT '',\n        reply TEXT DEFAULT '',\n        status TEXT DEFAULT 'new',\n        feedback TEXT DEFAULT '',\n        channel_title TEXT DEFAULT '',\n        channel_id TEXT DEFAULT '',\n        unlocked INTEGER DEFAULT 0,\n        UNIQUE(workspace_id, comment_id)\n    );\n    CREATE TABLE IF NOT EXISTS jobs (\n        id INTEGER PRIMARY KEY,\n        workspace_id INTEGER,\n        user_id INTEGER DEFAULT 1,\n        type TEXT,\n        status TEXT DEFAULT 'running',\n        msg TEXT DEFAULT '',\n        progress INTEGER DEFAULT 0,\n        result TEXT DEFAULT '',\n        error TEXT DEFAULT '',\n        created_at TEXT,\n        updated_at TEXT\n    );\n    CREATE TABLE IF NOT EXISTS upgrade_interest (\n        id INTEGER PRIMARY KEY,\n        user_id INTEGER,\n        plan TEXT,\n        created_at TEXT\n    );\n    CREATE TABLE IF NOT EXISTS runs (\n        id INTEGER PRIMARY KEY,\n        workspace_id INTEGER,\n        user_id INTEGER DEFAULT 1,\n        units_used INTEGER DEFAULT 0,\n        new_leads_count INTEGER DEFAULT 0,\n        status TEXT DEFAULT 'completed',\n        details TEXT DEFAULT '',\n        created_at TEXT\n    );\n    CREATE TABLE IF NOT EXISTS email_logs (\n        id INTEGER PRIMARY KEY,\n        user_id INTEGER DEFAULT 1,\n        to_email TEXT,\n        subject TEXT,\n        body TEXT,\n        email_type TEXT DEFAULT 'lead_alert',\n        provider TEXT DEFAULT 'supabase',\n        status TEXT DEFAULT 'sent',\n        created_at TEXT\n    );\n    ")
    ws_cols = [r[1] for r in conn.execute('PRAGMA table_info(workspaces)').fetchall()]
    if 'user_id' not in ws_cols:
        conn.execute('ALTER TABLE workspaces ADD COLUMN user_id INTEGER DEFAULT 1')
    if 'blocklist' not in ws_cols:
        conn.execute("ALTER TABLE workspaces ADD COLUMN blocklist TEXT DEFAULT ''")
    if 'profile' not in ws_cols:
        conn.execute("ALTER TABLE workspaces ADD COLUMN profile TEXT NOT NULL DEFAULT '{}'")
    lead_cols = [r[1] for r in conn.execute('PRAGMA table_info(leads)').fetchall()]
    if 'feedback' not in lead_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN feedback TEXT DEFAULT ''")
    if 'channel_title' not in lead_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN channel_title TEXT DEFAULT ''")
    if 'unlocked' not in lead_cols:
        conn.execute('ALTER TABLE leads ADD COLUMN unlocked INTEGER DEFAULT 0')
    if 'channel_id' not in lead_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN channel_id TEXT DEFAULT ''")
    additions = {'published_at': "TEXT DEFAULT ''", 'source_updated_at': "TEXT DEFAULT ''", 'buyer_type': "TEXT DEFAULT 'unknown'", 'evidence': "TEXT DEFAULT '{}'", 'analysis_revision': "TEXT DEFAULT ''", 'analysis_state': "TEXT DEFAULT 'legacy'", 'outcome': "TEXT DEFAULT 'new'", 'revenue_minor': 'INTEGER DEFAULT 0', 'currency': "TEXT DEFAULT ''", 'rejection_reason': "TEXT DEFAULT ''", 'outcome_updated_at': "TEXT DEFAULT ''"}
    for column, definition in additions.items():
        if column not in lead_cols:
            conn.execute(f'ALTER TABLE leads ADD COLUMN {column} {definition}')
    if 'pilot_feedback' not in ws_cols:
        conn.execute("ALTER TABLE workspaces ADD COLUMN pilot_feedback TEXT DEFAULT '{}'")
    conn.executescript("\n    CREATE TABLE IF NOT EXISTS api_usage (\n        id INTEGER PRIMARY KEY, run_id INTEGER, user_id INTEGER, workspace_id INTEGER,\n        provider TEXT NOT NULL, operation TEXT NOT NULL, bucket TEXT NOT NULL,\n        units INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,\n        cost_usd REAL, status TEXT DEFAULT 'started', created_at TEXT NOT NULL\n    );\n    CREATE INDEX IF NOT EXISTS api_usage_bucket_date ON api_usage(bucket, created_at);\n    CREATE INDEX IF NOT EXISTS api_usage_workspace ON api_usage(workspace_id);\n    CREATE TABLE IF NOT EXISTS integration_state (\n        provider TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL\n    );\n    CREATE TABLE IF NOT EXISTS lead_outcome_events (\n        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, user_id INTEGER NOT NULL,\n        previous_outcome TEXT, outcome TEXT NOT NULL, revenue_minor INTEGER DEFAULT 0,\n        currency TEXT DEFAULT '', rejection_reason TEXT DEFAULT '', created_at TEXT NOT NULL\n    );\n    CREATE INDEX IF NOT EXISTS outcome_events_lead ON lead_outcome_events(lead_id, created_at);\n    ")
    job_cols = [r[1] for r in conn.execute('PRAGMA table_info(jobs)').fetchall()]
    if 'user_id' not in job_cols:
        conn.execute('ALTER TABLE jobs ADD COLUMN user_id INTEGER DEFAULT 1')
    run_cols = [r[1] for r in conn.execute('PRAGMA table_info(runs)').fetchall()]
    if 'search_calls' not in run_cols:
        conn.execute('ALTER TABLE runs ADD COLUMN search_calls INTEGER DEFAULT 0')
    if 'user_id' not in run_cols:
        conn.execute('ALTER TABLE runs ADD COLUMN user_id INTEGER DEFAULT 1')
    user_cols = [r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
    if 'plan' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
        conn.execute("UPDATE users SET plan='unlimited' WHERE id=1")
    if 'name' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT 'Guna Shekar'")
        conn.execute("UPDATE users SET name='Guna Shekar' WHERE id=1")
    if 'supabase_uid' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN supabase_uid TEXT DEFAULT ''")
    default_user = conn.execute('SELECT id FROM users LIMIT 1').fetchone()
    if not default_user:
        now = core.datetime.now(core.timezone.utc).isoformat()
        pwd_hash = core.hash_password(core.secrets.token_urlsafe(48))
        conn.execute("INSERT INTO users(id, email, password_hash, created_at, plan, name) VALUES (1, 'founder@comment-money.local', ?, ?, 'unlimited', 'Guna Shekar')", (pwd_hash, now))
    legacy = conn.execute("SELECT password_hash FROM users WHERE id=1 AND email='founder@comment-money.local'").fetchone()
    if legacy and core.verify_password(legacy['password_hash'], 'demo1234'):
        conn.execute('UPDATE users SET password_hash=? WHERE id=1', (core.hash_password(core.secrets.token_urlsafe(48)),))
    core.commerce.schema(conn)
    conn.execute("UPDATE analysis_credits SET status='failed' WHERE status='reserved'")
    conn.execute("UPDATE jobs SET status='interrupted', error='Server restarted while job was running' WHERE status='running'")
    conn.execute("UPDATE jobs SET status='queued',error='',msg='Resuming saved request after restart' WHERE status='interrupted' AND payload!=''")
    conn.commit()
    conn.close()
