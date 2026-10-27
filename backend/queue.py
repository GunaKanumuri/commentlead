"""Queue service."""
from backend import commercial as core

def funding_class(ctx):
    if ctx.get('maintenance'):
        return 'maintenance'
    if not ctx.get('user_id'):
        return 'public'
    return 'free' if core.plan_of(ctx['user_id'])['key'] == 'free' else 'paid'

def source_hidden_sql():
    return 'retention_expired=0'

def submit_job(fn, jid, *args, **kwargs):
    if core.os.getenv('JOB_EXECUTION_MODE') == 'inline':
        core.threading.Thread(target=fn, args=(jid, *args), kwargs=kwargs, daemon=True).start()
        return
    payload = core.json.dumps({'function': fn.__name__, 'args': [jid, *args], 'kwargs': kwargs})
    conn = core.R['get_db']()
    try:
        conn.execute("UPDATE jobs SET payload=?,status='queued',msg='Queued for fair processing' WHERE id=?", (payload, jid))
        conn.commit()
    finally:
        conn.close()

def work_queue():
    if core.os.getenv('JOB_EXECUTION_MODE') == 'inline' or not core.R.get('_COMMERCIAL_READY'):
        return
    maximum = max(1, min(int(core.os.getenv('MAX_ACTIVE_JOBS', '2')), 8))
    conn = core.R['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] >= maximum:
            return
        turns = conn.execute("SELECT COUNT(*) FROM jobs WHERE COALESCE(started_at,'')!=''").fetchone()[0]
        prefer_free = turns % 5 == 4
        rows = conn.execute("SELECT j.*,u.plan FROM jobs j JOIN users u ON u.id=j.user_id WHERE j.status='queued' AND j.payload!='' AND COALESCE(u.deleted_at,'')='' AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.user_id=j.user_id AND d.status!='done')\n            ORDER BY CASE WHEN u.plan='free' THEN ? ELSE ? END,\n            COALESCE((SELECT MAX(p.started_at) FROM jobs p WHERE p.user_id=j.user_id),''),j.created_at LIMIT 20", (0 if prefer_free else 1, 1 if prefer_free else 0)).fetchall()
        if not rows:
            return
        row = rows[0]
        conn.execute("UPDATE jobs SET status='running',started_at=? WHERE id=? AND status='queued'", (core.iso(core.now()), row['id']))
        conn.commit()
        payload = core.json.loads(row['payload'])
    finally:
        conn.close()
    fn = core.R.get(payload['function'])
    if payload['function'] not in ('run_auto_job', 'run_scan_job', 'run_reassessment') or fn is None:
        core.R['update_job'](row['id'], status='error', error='Invalid queued task')
        return

    def execute():
        try:
            fn(*payload['args'], **payload['kwargs'])
        except Exception:
            core.R['update_job'](row['id'], status='error', error='Worker failed; retry your saved request')
    core.threading.Thread(target=execute, daemon=True).start()

def plan_status(authorization=None):
    user = core.R['get_current_user'](authorization)
    conn = core.R['get_db']()
    try:
        plan = core.plan_of(user['id'], conn)
        for ws in conn.execute('SELECT id FROM workspaces WHERE user_id=?', (user['id'],)).fetchall():
            core.unlock_top_leads(conn, user['id'], ws['id'])
        used = core.searches_used(conn, user['id'])
        grants = conn.execute('SELECT COUNT(*) FROM match_grants WHERE user_id=? AND period_key=?', (user['id'], plan['period_key'])).fetchone()[0]
        locked = conn.execute("SELECT l.score FROM leads l JOIN workspaces w ON w.id=l.workspace_id WHERE w.user_id=? AND l.unlocked=0 AND l.score>=60 AND retention_expired=0 AND COALESCE(l.feedback,'')!='bad'", (user['id'],)).fetchall()
        return dict(plan, plan=plan['key'], searches_limit=plan['searches'], searches_used=used, leads_limit=plan['leads'], leads_unlocked=grants, locked_total=len(locked), locked_strong=sum((r[0] >= 80 for r in locked)), analysis_remaining=core.remaining_analysis(conn, user['id']), can_search=not plan['trial_expired'] and core.remaining_analysis(conn, user['id']) > 0 and (plan['searches'] is None or used < plan['searches']))
    finally:
        conn.close()
