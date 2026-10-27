"""Entitlements service."""
from backend import commercial as core

def now():
    return core.datetime.now(core.timezone.utc)

def iso(value):
    return value.astimezone(core.timezone.utc).isoformat()

def parse(value):
    try:
        return core.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

def next_month(value):
    year = value.year + (value.month == 12)
    month = value.month % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, core.calendar.monthrange(year, month)[1]))

def schema(conn):
    if core.R.get('database') and core.R['database'].is_postgres():
        return
    columns = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    for key, definition in {'billing_start': "TEXT DEFAULT ''", 'billing_end': "TEXT DEFAULT ''", 'email_verified': 'INTEGER DEFAULT 0', 'trial_started_at': "TEXT DEFAULT ''", 'deleted_at': "TEXT DEFAULT ''"}.items():
        if key not in columns:
            conn.execute(f'ALTER TABLE users ADD COLUMN {key} {definition}')
    columns = {r[1] for r in conn.execute('PRAGMA table_info(leads)')}
    for key, definition in {'retrieved_at': "TEXT DEFAULT ''", 'retention_expired': 'INTEGER DEFAULT 0'}.items():
        if key not in columns:
            conn.execute(f'ALTER TABLE leads ADD COLUMN {key} {definition}')
    columns = {r[1] for r in conn.execute('PRAGMA table_info(jobs)')}
    for key, definition in {'payload': "TEXT DEFAULT ''", 'started_at': "TEXT DEFAULT ''", 'execution_error': "TEXT DEFAULT ''"}.items():
        if key not in columns:
            conn.execute(f'ALTER TABLE jobs ADD COLUMN {key} {definition}')
    columns = {r[1] for r in conn.execute('PRAGMA table_info(api_usage)')}
    if 'funding' not in columns:
        conn.execute("ALTER TABLE api_usage ADD COLUMN funding TEXT DEFAULT 'legacy'")
    conn.executescript("\n    CREATE TABLE IF NOT EXISTS match_grants(user_id INTEGER,lead_id INTEGER,period_key TEXT,created_at TEXT,PRIMARY KEY(user_id,lead_id));\n    CREATE INDEX IF NOT EXISTS match_grants_period ON match_grants(user_id,period_key);\n    CREATE TABLE IF NOT EXISTS analysis_credits(id TEXT PRIMARY KEY,user_id INTEGER,period_key TEXT,amount INTEGER,status TEXT,created_at TEXT);\n    CREATE INDEX IF NOT EXISTS analysis_credits_period ON analysis_credits(user_id,period_key,status);\n    CREATE TABLE IF NOT EXISTS request_limits(scope TEXT,identity TEXT,window INTEGER,count INTEGER,PRIMARY KEY(scope,identity,window));\n    CREATE TABLE IF NOT EXISTS trial_claims(identity TEXT PRIMARY KEY,user_id INTEGER,kind TEXT,created_at TEXT);\n    CREATE TABLE IF NOT EXISTS policy_acceptance(user_id INTEGER,version TEXT,accepted_at TEXT,PRIMARY KEY(user_id,version));\n    CREATE TABLE IF NOT EXISTS billing_subscriptions(id TEXT PRIMARY KEY,user_id INTEGER,plan TEXT,status TEXT,created_at TEXT);\n    CREATE UNIQUE INDEX IF NOT EXISTS billing_one_open_subscription ON billing_subscriptions(user_id) WHERE status IN ('creating','created','authenticated','active','pending');\n    CREATE TABLE IF NOT EXISTS billing_events(id TEXT PRIMARY KEY,payload_hash TEXT,created_at TEXT);\n    CREATE TABLE IF NOT EXISTS deletion_requests(user_id INTEGER PRIMARY KEY,requested_at TEXT,status TEXT,error TEXT DEFAULT '');\n    CREATE TABLE IF NOT EXISTS lifecycle_sync(lead_id INTEGER PRIMARY KEY,updated_at TEXT,error TEXT DEFAULT '');\n    CREATE TABLE IF NOT EXISTS lifecycle_cleanup_tasks(task TEXT PRIMARY KEY,updated_at TEXT,error TEXT DEFAULT '');\n    ")
    start = core.now()
    conn.execute("UPDATE users SET billing_start=?,billing_end=? WHERE plan IN ('starter','pro') AND COALESCE(billing_end,'')=''", (core.iso(start), core.iso(core.next_month(start))))
    conn.execute("INSERT OR IGNORE INTO match_grants SELECT w.user_id,l.id,'legacy',? FROM leads l JOIN workspaces w ON w.id=l.workspace_id WHERE l.unlocked=1", (core.iso(start),))

def plan_of(user_id, conn=None):
    own = conn is None
    if own:
        conn = core.R['get_db']()
    row = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    data = dict(row) if row else {}
    key = data.get('plan', 'free')
    if key == 'unlimited':
        out = dict(core.INTERNAL_PLAN, key=key, period_key='internal', period_start='', period_end='', trial_expired=False)
    else:
        if key not in core.PUBLIC_PLANS:
            key = 'free'
        if key != 'free' and (not core.parse(data.get('billing_end')) or core.parse(data['billing_end']) <= core.now()):
            key = 'free'
        start = data.get('billing_start', '') if key != 'free' else data.get('trial_started_at', '')
        end = data.get('billing_end', '') if key != 'free' else core.iso(core.parse(start) + core.timedelta(days=7)) if core.parse(start) else ''
        out = dict(core.PUBLIC_PLANS[key], key=key, period_key=start if key != 'free' else 'trial', period_start=start, period_end=end, trial_expired=key == 'free' and bool(end) and (core.parse(end) <= core.now()))
    if own:
        conn.close()
    return out

def searches_used(conn, user_id):
    plan = core.plan_of(user_id, conn)
    sql = "SELECT COUNT(*) FROM jobs WHERE user_id=? AND type IN ('auto','scan') AND status IN ('queued','running','done')"
    args = [user_id]
    if plan['key'] not in ('free', 'unlimited'):
        sql += ' AND created_at>=? AND created_at<?'
        args += [plan['period_start'], plan['period_end']]
    return conn.execute(sql, args).fetchone()[0]

def remaining_analysis(conn, user_id):
    plan = core.plan_of(user_id, conn)
    if plan['analysis'] is None:
        return 10 ** 9
    used = conn.execute("SELECT COALESCE(SUM(amount),0) FROM analysis_credits WHERE user_id=? AND period_key=? AND status IN ('reserved','used')", (user_id, plan['period_key'])).fetchone()[0]
    return max(0, plan['analysis'] - used)

def reserve_analysis(user_id, requested):
    conn = core.R['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE')
        plan = core.plan_of(user_id, conn)
        if plan['trial_expired']:
            raise core.HTTPException(403, 'Your trial has ended. Choose a paid plan to continue.')
        allowed = min(requested, core.remaining_analysis(conn, user_id))
        if allowed <= 0:
            raise core.HTTPException(403, 'Comment-analysis allowance exhausted for this period')
        token = core.secrets.token_hex(16)
        conn.execute('INSERT INTO analysis_credits VALUES(?,?,?,?,?,?)', (token, user_id, plan['period_key'], allowed, 'reserved', core.iso(core.now())))
        conn.commit()
        return (token, allowed)
    finally:
        conn.close()

def settle_analysis(token, success):
    conn = core.R['get_db']()
    try:
        conn.execute('UPDATE analysis_credits SET status=? WHERE id=?', ('used' if success else 'failed', token))
        conn.commit()
    finally:
        conn.close()

def unlock_top_leads(conn, user_id, wid):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    plan = core.plan_of(user_id, conn)
    cap = plan['leads']
    if plan['trial_expired']:
        return
    if cap is None:
        return
    used = conn.execute('SELECT COUNT(*) FROM match_grants WHERE user_id=? AND period_key=?', (user_id, plan['period_key'])).fetchone()[0]
    room = max(0, cap - used)
    if not room:
        return
    ws = conn.execute('SELECT blocklist FROM workspaces WHERE id=?', (wid,)).fetchone()
    for row in conn.execute("SELECT * FROM leads WHERE workspace_id=? AND unlocked=0 AND score>=60 AND retention_expired=0 AND COALESCE(feedback,'')!='bad' ORDER BY score DESC,id", (wid,)).fetchall():
        if not core.source_visible(row) or core.R['is_blocked'](row['author'], row['text'], ws['blocklist'] or ''):
            continue
        conn.execute('INSERT OR IGNORE INTO match_grants VALUES(?,?,?,?)', (user_id, row['id'], plan['period_key'], core.iso(core.now())))
        conn.execute('UPDATE leads SET unlocked=1 WHERE id=?', (row['id'],))
        room -= 1
        if not room:
            break
    conn.commit()

def product_limit(conn, user_id, existing_id=None):
    plan = core.plan_of(user_id, conn)
    if plan['products'] is None or existing_id:
        return
    used = conn.execute("SELECT COUNT(*) FROM workspaces WHERE user_id=? AND length(trim(COALESCE(pitch,'')))>10", (user_id,)).fetchone()[0]
    if used >= plan['products']:
        raise core.HTTPException(403, f"{plan['label']} supports {plan['products']} product(s); upgrade or edit an existing product")

def identity_hash(value):
    return core.hmac.new(core.R['JWT_SECRET'].encode(), value.encode(), core.hashlib.sha256).hexdigest()

def canonical_email(email):
    local, _, domain = email.strip().lower().partition('@')
    if domain in ('gmail.com', 'googlemail.com'):
        local = local.split('+', 1)[0].replace('.', '')
        domain = 'gmail.com'
    return local + '@' + domain

def rate_limit(scope, identity, limit, seconds):
    window = int(core.now().timestamp()) // seconds
    key = core.identity_hash(identity)
    conn = core.R['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT count FROM request_limits WHERE scope=? AND identity=? AND "window"=?', (scope, key, window)).fetchone()
        if row and row[0] >= limit:
            raise core.HTTPException(429, 'Too many requests. Please try again later.')
        conn.execute('INSERT INTO request_limits VALUES(?,?,?,1) ON CONFLICT(scope,identity,"window") DO UPDATE SET count=request_limits.count+1', (scope, key, window))
        conn.execute('DELETE FROM request_limits WHERE "window"<? AND scope=?', (window - 2, scope))
        conn.commit()
    finally:
        conn.close()

def claim_trial(user_id, request=None):
    conn = core.R['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE')
        user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        conn.execute('DELETE FROM trial_claims WHERE created_at<?', (core.iso(core.now() - core.timedelta(days=180)),))
        plan = core.plan_of(user_id, conn)
        if plan['key'] != 'free':
            return
        if core.os.getenv('APP_ENV') == 'production' and (not user['email_verified']):
            raise core.HTTPException(403, 'Verify your email before starting the free trial')
        if plan['trial_expired']:
            raise core.HTTPException(403, 'The seven-day trial has ended')
        identities = [('email', core.canonical_email(user['email']))]
        if request is not None:
            device = getattr(request.state, 'trial_device', '')
            if device:
                identities.append(('device', device))
        for kind, value in identities:
            key = core.identity_hash(kind + ':' + value)
            existing = conn.execute('SELECT user_id FROM trial_claims WHERE identity=?', (key,)).fetchone()
            if existing and existing['user_id'] != user_id:
                raise core.HTTPException(403, 'A trial has already been used for this email or browser. Sign in to that account or choose a paid plan.')
            conn.execute('INSERT OR IGNORE INTO trial_claims VALUES(?,?,?,?)', (key, user_id, kind, core.iso(core.now())))
        if not user['trial_started_at']:
            conn.execute('UPDATE users SET trial_started_at=? WHERE id=?', (core.iso(core.now()), user_id))
        conn.commit()
    finally:
        conn.close()

def public_catalog():
    return [dict(value, key=key, currency='INR', period='one-time seven-day trial' if key == 'free' else 'billing month') for key, value in core.PUBLIC_PLANS.items()]

def protect_request(request):
    cookie = request.cookies.get('cm_trial_device', '')
    parts = cookie.split('.')
    if len(parts) == 2 and core.re.fullmatch('[a-f0-9]{32}', parts[0]) and core.hmac.compare_digest(core.identity_hash('device-cookie:' + parts[0]), parts[1]):
        device = parts[0]
    else:
        device = core.secrets.token_hex(16)
    request.state.trial_device = device
    ip = request.client.host if request.client else 'unknown'
    path = request.url.path
    if request.method == 'POST':
        if path.endswith('/auth/register'):
            core.rate_limit('signup', ip, 5, 86400)
        elif path.endswith('/auth/login') or path.endswith('/auth/supabase-sync'):
            core.rate_limit('login', ip, 15, 600)
        elif any((path.endswith('/auth/' + name) for name in ('magic-link', 'forgot-password', 'resend-confirmation'))):
            core.rate_limit('auth-email', ip, 3, 3600)
        elif path.endswith('/free-preview'):
            core.rate_limit('preview', ip, 3, 3600)
            if core.os.getenv('APP_ENV') == 'production' and core.os.getenv('YOUTUBE_USE_CASE_APPROVED') != 'true':
                raise core.HTTPException(503, 'Preview processing is not enabled for public launch')
            if core.os.getenv('APP_ENV') == 'production' and (not core.hmac.compare_digest(request.cookies.get('cm_policy', ''), core.POLICY_VERSION + '.' + core.identity_hash('consent:' + core.POLICY_VERSION))):
                raise core.HTTPException(403, 'Read and accept the Terms and Privacy Policy before previewing comments')
        elif path.endswith('/billing/checkout'):
            core.rate_limit('checkout', ip, 5, 3600)

def require_processing(user_id, request=None):
    conn = core.R['get_db']()
    try:
        deleting = conn.execute("SELECT 1 FROM deletion_requests WHERE user_id=? AND status!='done'", (user_id,)).fetchone()
    finally:
        conn.close()
    if deleting:
        raise core.HTTPException(403, 'Account deletion is in progress')
    if core.os.getenv('APP_ENV') == 'production':
        if core.os.getenv('YOUTUBE_USE_CASE_APPROVED') != 'true':
            raise core.HTTPException(503, 'This processing feature is not enabled for public launch')
        conn = core.R['get_db']()
        try:
            accepted = conn.execute('SELECT 1 FROM policy_acceptance WHERE user_id=? AND version=?', (user_id, core.POLICY_VERSION)).fetchone()
        finally:
            conn.close()
        if not accepted:
            raise core.HTTPException(403, 'Read and accept the current Terms and Privacy Policy first')
    if request is not None:
        conn = core.R['get_db']()
        try:
            user = conn.execute('SELECT trial_started_at FROM users WHERE id=?', (user_id,)).fetchone()
        finally:
            conn.close()
        if user and (not user[0]) and (core.plan_of(user_id)['key'] == 'free'):
            core.rate_limit('new-trials', request.client.host if request.client else 'unknown', 2, 86400)
    core.claim_trial(user_id, request)

def verified_email(user_id, verified):
    if not verified:
        return
    conn = core.R['get_db']()
    try:
        conn.execute('UPDATE users SET email_verified=1 WHERE id=?', (user_id,))
        conn.commit()
    finally:
        conn.close()
