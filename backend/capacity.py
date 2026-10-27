"""Capacity: focused API/service functions."""
from backend import runtime as core

def quota_day_start_utc() -> str:
    """YouTube's daily quota resets at midnight Pacific Time, not UTC."""
    try:
        tz = core.ZoneInfo('America/Los_Angeles')
    except Exception:
        tz = core.timezone(core.timedelta(hours=-8))
    now = core.datetime.now(tz)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(core.timezone.utc).isoformat()

def get_today_quota_used(user_id: int=None):
    conn = core.get_db()
    start = core.quota_day_start_utc()
    if user_id:
        res = conn.execute('SELECT COALESCE(SUM(units_used), 0) FROM runs WHERE user_id=? AND created_at >= ?', (user_id, start)).fetchone()
    else:
        res = conn.execute('SELECT COALESCE(SUM(units_used), 0) FROM runs WHERE created_at >= ?', (start,)).fetchone()
    conn.close()
    return int(res[0]) if res else 0

def plan_of(user_id: int, conn=None) -> dict:
    return core.commerce.plan_of(user_id, conn)

def searches_used(conn, user_id):
    return core.commerce.searches_used(conn, user_id)

def reserve_search(user_id: int, wid: int, kind: str, est_units: int, msg: str='Starting search...'):
    """Atomically check plan limit + shared YouTube budget, then create the job and a quota reservation."""
    core.commerce.require_processing(user_id)
    conn = core.get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        plan = core.plan_of(user_id, conn)
        if core.commerce.remaining_analysis(conn, user_id) <= 0:
            raise core.HTTPException(403, 'Comment-analysis allowance exhausted for this period')
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('running','queued')", (user_id,)).fetchone()[0]:
            raise core.HTTPException(409, 'A search is already running. Please wait for it to finish.')
        if kind != 'reassess' and plan['searches'] is not None and (core.searches_used(conn, user_id) >= plan['searches']):
            raise core.HTTPException(403, f"You have used your {plan['searches']} included searches. Upgrade to keep finding leads.")
        start = core.quota_day_start_utc()
        search_calls = plan['queries'] if kind == 'auto' else 0
        allocated_search = conn.execute('SELECT COALESCE(SUM(search_calls),0) FROM runs WHERE created_at>=?', (start,)).fetchone()[0]
        public_search = conn.execute("SELECT COALESCE(SUM(units),0) FROM api_usage WHERE bucket='youtube_search' AND run_id IS NULL AND created_at>=?", (start,)).fetchone()[0]
        if allocated_search + public_search + search_calls > core.DAILY_SEARCH_BUDGET:
            raise core.HTTPException(429, 'YouTube search capacity is full for today; no search was charged')
        if search_calls:
            funding = 'free' if plan['key'] == 'free' else 'paid'
            funding_cap = int(core.os.getenv('TRIAL_DAILY_SEARCH_BUDGET', '10') if funding == 'free' else core.os.getenv('PAID_DAILY_SEARCH_BUDGET', '75'))
            pool_reserved = conn.execute("SELECT COALESCE(SUM(r.search_calls),0) FROM runs r LEFT JOIN users u ON u.id=r.user_id\n                WHERE r.created_at>=? AND COALESCE((SELECT a.funding FROM api_usage a WHERE a.run_id=r.id AND a.bucket='youtube_search' LIMIT 1),\n                CASE WHEN COALESCE(u.plan,'free')='free' THEN 'free' ELSE 'paid' END)=?", (start, funding)).fetchone()[0]
            pool_unreserved = conn.execute("SELECT COALESCE(SUM(units),0) FROM api_usage WHERE bucket='youtube_search' AND funding=? AND run_id IS NULL AND created_at>=?", (funding, start)).fetchone()[0]
            if pool_reserved + pool_unreserved + search_calls > funding_cap:
                raise core.HTTPException(429, 'This capacity pool is full today; no discovery run was charged')
        total = conn.execute('SELECT COALESCE(SUM(units_used),0) FROM runs WHERE created_at >= ?', (start,)).fetchone()[0]
        free_total = conn.execute("SELECT COALESCE(SUM(r.units_used),0) FROM runs r LEFT JOIN users u ON u.id=r.user_id WHERE r.created_at >= ? AND COALESCE(u.plan,'free')='free'", (start,)).fetchone()[0]
        busy = 'Search capacity is full for today. Please try again tomorrow. This did not use one of your searches.'
        if kind != 'reassess' and total + est_units > core.DAILY_QUOTA_BUDGET:
            raise core.HTTPException(429, busy)
        if kind != 'reassess' and plan['key'] == 'free' and (free_total + est_units > core.DAILY_QUOTA_BUDGET * core.FREE_QUOTA_SHARE):
            raise core.HTTPException(429, busy)
        now = core.datetime.now(core.timezone.utc).isoformat()
        jid = conn.execute("INSERT INTO jobs(workspace_id, user_id, type, status, msg, progress, created_at, updated_at) VALUES (?,?,?,'queued',?,0,?,?)", (wid, user_id, kind, msg, now, now)).lastrowid
        run_id = conn.execute("INSERT INTO runs(workspace_id, user_id, units_used, search_calls, new_leads_count, status, details, created_at) VALUES (?,?,?,?,0,'reserved',?,?)", (wid, user_id, est_units, search_calls, f'{kind} search', now)).lastrowid
        conn.commit()
        return (jid, run_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def finish_run(run_id, status: str, new_leads: int=None, details: str=None, units: int=None):
    if not run_id:
        return
    conn = core.get_db()
    sets, vals = (['status=?'], [status])
    if new_leads is not None:
        sets.append('new_leads_count=?')
        vals.append(new_leads)
    if details is not None:
        sets.append('details=?')
        vals.append(details)
    if units is not None:
        sets.append('units_used=?')
        vals.append(units)
    vals.append(run_id)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    core.sb_sync_run_row(run_id)

def unlock_top_leads(conn, user_id, wid):
    return core.commerce.unlock_top_leads(conn, user_id, wid)

def alertable(conn, user_id: int, wid: int, leads: list):
    """Only leads the user may see go into alert emails/Telegram. Returns (visible_leads, hidden_count)."""
    if core.plan_of(user_id, conn)['leads'] is None or not leads:
        return (leads, 0)
    ok = {r[0] for r in conn.execute('SELECT comment_id FROM leads WHERE workspace_id=? AND unlocked=1', (wid,))}
    shown = [l for l in leads if l.get('id') in ok]
    return (shown, len(leads) - len(shown))

def begin_api_call(provider, operation):
    ctx = core._API_CONTEXT.get()
    bucket = 'youtube_search' if provider == 'youtube' and operation == 'search' else 'youtube_other' if provider == 'youtube' else 'gemini'
    limit = core.DAILY_SEARCH_BUDGET if bucket == 'youtube_search' else core.DAILY_QUOTA_BUDGET if bucket == 'youtube_other' else int(core.os.getenv('GEMINI_DAILY_REQUEST_BUDGET', '1000'))
    funding = core.commerce.funding_class(ctx)
    conn = core.get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        used = conn.execute('SELECT COALESCE(SUM(units),0) FROM api_usage WHERE bucket=? AND created_at>=?', (bucket, core.quota_day_start_utc())).fetchone()[0]
        if used >= limit:
            raise core.HTTPException(429, f"Daily {bucket.replace('_', ' ')} capacity reached. Try after midnight Pacific Time.")
        if ctx.get('user_id') and core.plan_of(ctx['user_id'], conn)['key'] == 'free' and bucket.startswith('youtube'):
            free_used = conn.execute("SELECT COALESCE(SUM(a.units),0) FROM api_usage a JOIN users u ON u.id=a.user_id\n                WHERE a.bucket=? AND a.created_at>=? AND u.plan='free'", (bucket, core.quota_day_start_utc())).fetchone()[0]
            if free_used >= int(limit * core.FREE_QUOTA_SHARE):
                raise core.HTTPException(429, 'Free search capacity is full for today')
        if bucket == 'youtube_search':
            funding_cap = {'paid': int(core.os.getenv('PAID_DAILY_SEARCH_BUDGET', '75')), 'free': int(core.os.getenv('TRIAL_DAILY_SEARCH_BUDGET', '10')), 'public': int(core.os.getenv('PREVIEW_DAILY_SEARCH_BUDGET', '5')), 'maintenance': 0}[funding]
            spent = conn.execute('SELECT COALESCE(SUM(units),0) FROM api_usage WHERE bucket=? AND funding=? AND created_at>=?', (bucket, funding, core.quota_day_start_utc())).fetchone()[0]
            if spent >= funding_cap:
                raise core.HTTPException(429, 'This service capacity pool is full for today; paid capacity is reserved separately')
        if bucket=='gemini' and funding=='public':
            public_cap=int(core.os.getenv('PREVIEW_DAILY_AI_REQUEST_BUDGET','20'))
            public_used=conn.execute("SELECT COALESCE(SUM(units),0) FROM api_usage WHERE bucket='gemini' AND funding='public' AND created_at>=?",(core.quota_day_start_utc(),)).fetchone()[0]
            if public_used>=public_cap:
                raise core.HTTPException(429,'Free product-matching capacity is full for today. Try again tomorrow.')
        if bucket == 'gemini' and ctx.get('user_id'):
            per_user = int(core.os.getenv('GEMINI_REQUESTS_PER_USER_DAY', '50'))
            spent = conn.execute("SELECT COUNT(*) FROM api_usage WHERE provider='gemini' AND user_id=? AND created_at>=?", (ctx['user_id'], core.quota_day_start_utc())).fetchone()[0]
            if spent >= per_user:
                raise core.HTTPException(429, 'Daily AI allowance reached for this account')
        uid = conn.execute('INSERT INTO api_usage(run_id,user_id,workspace_id,provider,operation,bucket,units,cost_usd,created_at,funding)\n            VALUES(?,?,?,?,?,?,1,?,?,?)', (ctx.get('run_id'), ctx.get('user_id'), ctx.get('workspace_id'), provider, operation, bucket, 0 if provider == 'youtube' else None, core.datetime.now(core.timezone.utc).isoformat(), funding)).lastrowid
        conn.commit()
        return uid
    finally:
        conn.close()

def complete_api_call(uid, status, metadata=None, model=None):
    metadata = metadata if isinstance(metadata, dict) else {}
    incoming = int(metadata.get('promptTokenCount') or 0)
    outgoing = max(int(metadata.get('candidatesTokenCount') or 0) + int(metadata.get('thoughtsTokenCount') or 0), int(metadata.get('totalTokenCount') or 0) - incoming)
    cost = None
    rates = core.json_object(core.os.getenv('GEMINI_PRICING_JSON')).get(model, {})
    if metadata and isinstance(rates, dict):
        try:
            cost = float((core.Decimal(str(rates['input_usd_per_million'])) * incoming + core.Decimal(str(rates['output_usd_per_million'])) * outgoing) / 1000000)
            if cost < 0:
                cost = None
        except (KeyError, ValueError, ArithmeticError):
            pass
    conn = core.get_db()
    try:
        conn.execute('UPDATE api_usage SET status=?,input_tokens=?,output_tokens=?,cost_usd=COALESCE(?,cost_usd) WHERE id=?', (status, incoming, outgoing, cost, uid))
        conn.commit()
        provider = conn.execute('SELECT provider FROM api_usage WHERE id=?', (uid,)).fetchone()[0]
    finally:
        conn.close()
    core.integration_status(provider, status)

def track_run(fn):

    @core.wraps(fn)
    def wrapped(*args, **kwargs):
        params = core.signature(fn).bind_partial(*args, **kwargs).arguments
        conn = core.get_db()
        row = conn.execute('SELECT user_id FROM workspaces WHERE id=?', (params.get('wid'),)).fetchone()
        conn.close()
        run_id = params.get('run_id')
        token = core._API_CONTEXT.set({'run_id': run_id, 'workspace_id': params.get('wid'), 'user_id': row['user_id'] if row else None})
        try:
            return fn(*args, **kwargs)
        finally:
            core._API_CONTEXT.reset(token)
            if run_id:
                conn = core.get_db()
                totals = conn.execute("SELECT COALESCE(SUM(CASE WHEN bucket='youtube_other' THEN units ELSE 0 END),0),\n                    COALESCE(SUM(CASE WHEN bucket='youtube_search' THEN units ELSE 0 END),0) FROM api_usage WHERE run_id=?", (run_id,)).fetchone()
                conn.execute('UPDATE runs SET units_used=?,search_calls=? WHERE id=?', (totals[0], totals[1], run_id))
                conn.commit()
                conn.close()
                core.sb_sync_run_row(run_id)
    return wrapped

@core.app.get('/api/admin/operations')
def operations(authorization: str=core.Header(None)):
    core.require_admin(authorization)
    conn = core.get_db()
    try:
        usage = [dict(r) for r in conn.execute('SELECT provider,bucket,status,COUNT(*) AS requests,\n            SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,SUM(cost_usd) AS estimated_cost_usd,\n            SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced_requests FROM api_usage\n            WHERE created_at>=? GROUP BY provider,bucket,status', (core.quota_day_start_utc(),))]
        failures = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='error' AND created_at>=?", (core.quota_day_start_utc(),)).fetchone()[0]
        return {'integrations': [dict(r) for r in conn.execute('SELECT * FROM integration_state')], 'usage_today': usage, 'failed_jobs_today': failures, 'search_budget': core.DAILY_SEARCH_BUDGET, 'other_units_budget': core.DAILY_QUOTA_BUDGET, 'note': 'Token costs are estimates using configured model prices; missing prices remain unknown. Hosting and outreach costs are excluded.'}
    finally:
        conn.close()
