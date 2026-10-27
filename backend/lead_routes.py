"""Lead Routes: focused API/service functions."""
from backend import runtime as core

@core.app.get('/api/leads/export')
def export_leads(workspace_id: int, min_score: int=60, status: str='new', authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    ws = core.check_ws_owner(conn, workspace_id, user['id'])
    ws_name = ws['name'] if ws and ws['name'] else f'workspace_{workspace_id}'
    blocklist_str = ws['blocklist'] if ws and 'blocklist' in ws.keys() and ws['blocklist'] else ''
    capped = core.plan_of(user['id'], conn)['leads'] is not None
    if capped:
        core.unlock_top_leads(conn, user['id'], workspace_id)
    if status in {'contacted', 'responded', 'qualified', 'purchased', 'irrelevant'}:
        rows = conn.execute('SELECT * FROM leads WHERE workspace_id=? AND score>=? AND outcome=? ORDER BY (score / 20) DESC, published_at DESC, score DESC', (workspace_id, min_score, status)).fetchall()
    elif status == 'all':
        rows = conn.execute('SELECT * FROM leads WHERE workspace_id=? AND score>=? ORDER BY (score / 20) DESC, published_at DESC, score DESC', (workspace_id, min_score)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM leads WHERE workspace_id=? AND score>=? AND status=? ORDER BY (score / 20) DESC, published_at DESC, score DESC', (workspace_id, min_score, status)).fetchall()
    conn.close()
    output = core.io.StringIO()
    writer = core.csv.writer(output)
    writer.writerow(['Score', 'Author', 'Video Title', 'Comment', 'Why (Reason)', 'Draft Reply', 'Status', 'Feedback', 'YouTube Comment Link', 'Published At', 'Buyer Type', 'Analysis Outdated', 'Outcome', 'Revenue Minor Units', 'Currency', 'Rejection Reason'])
    for r in rows:
        d = dict(r)
        if not core.commerce.source_visible(d):
            continue
        if core.is_blocked(d.get('author', ''), d.get('text', ''), blocklist_str):
            continue
        if capped and (not d.get('unlocked')):
            continue
        link = f"https://www.youtube.com/watch?v={r['video_id']}&lc={r['comment_id']}"
        feedback = r['feedback'] if 'feedback' in r.keys() and r['feedback'] else ''
        writer.writerow([r['score'], r['author'], r['video_title'], r['text'], r['reason'], r['reply'], r['status'], feedback, link, r['published_at'], r['buyer_type'], r['analysis_revision'] != core.workspace_revision(ws) or r['analysis_state'] != 'complete', r['outcome'], r['revenue_minor'], r['currency'], r['rejection_reason']])
    output.seek(0)
    safe_filename = core.re.sub('[^\\w\\-]', '_', ws_name).strip('_') or 'leads'
    return core.Response(content=output.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename=leads_{safe_filename}.csv'})

def owned_lead(conn, lid, user_id):
    row = conn.execute('SELECT l.*, w.user_id AS owner_id FROM leads l JOIN workspaces w ON w.id=l.workspace_id WHERE l.id=?', (lid,)).fetchone()
    if not row or not core.commerce.source_visible(row):
        raise core.HTTPException(404, 'Lead not found')
    if row['owner_id'] != user_id:
        raise core.HTTPException(403, 'Not authorized to modify this lead')
    if core.plan_of(user_id, conn)['leads'] is not None and (not row['unlocked']):
        raise core.HTTPException(403, 'Unlock this lead before recording an outcome')
    return row

@core.app.post('/api/leads/{lid}/outcome')
def set_outcome(lid: int, body: core.Outcome, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    reason = body.rejection_reason.strip()
    if body.stage == 'irrelevant' and (not reason):
        raise core.HTTPException(400, 'Please explain why this lead is irrelevant')
    if body.stage != 'purchased' and body.revenue:
        raise core.HTTPException(400, 'Revenue can only be recorded for a purchase')
    minor = int(body.revenue * 100) if body.stage == 'purchased' else 0
    currency = body.currency if body.stage == 'purchased' else ''
    reason = reason if body.stage == 'irrelevant' else ''
    now = core.datetime.now(core.timezone.utc).isoformat()
    conn = core.get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = core.owned_lead(conn, lid, user['id'])
        if (row['outcome'], row['revenue_minor'], row['currency'], row['rejection_reason']) != (body.stage, minor, currency, reason):
            status = 'new' if body.stage == 'new' else 'ignored' if body.stage == 'irrelevant' else 'replied'
            conn.execute('UPDATE leads SET outcome=?, revenue_minor=?, currency=?, rejection_reason=?,\n                outcome_updated_at=?, status=? WHERE id=?', (body.stage, minor, currency, reason, now, status, lid))
            conn.execute('INSERT INTO lead_outcome_events(lead_id,user_id,previous_outcome,outcome,revenue_minor,currency,rejection_reason,created_at)\n                VALUES(?,?,?,?,?,?,?,?)', (lid, user['id'], row['outcome'], body.stage, minor, currency, reason, now))
        conn.commit()
        saved = conn.execute('SELECT * FROM leads WHERE id=?', (lid,)).fetchone()
    finally:
        conn.close()
    core.sb_sync_leads_rows([saved])
    return {'ok': True, 'stage': body.stage, 'revenue_minor': minor, 'currency': currency}

@core.app.get('/api/workspaces/{wid}/metrics')
def workspace_metrics(wid: int, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    try:
        ws = core.check_ws_owner(conn, wid, user['id'])
        capped = core.plan_of(user['id'], conn)['leads'] is not None
        rows = [dict(r) for r in conn.execute('SELECT * FROM leads WHERE workspace_id=?', (wid,)) if not capped or r['unlocked']]
        funnel = {stage: sum((r['outcome'] == stage for r in rows)) for stage in ('new', 'contacted', 'responded', 'qualified', 'purchased', 'irrelevant')}
        revenue = {}
        for r in rows:
            if r['outcome'] == 'purchased' and r['currency']:
                revenue[r['currency']] = revenue.get(r['currency'], 0) + r['revenue_minor']
        usage = conn.execute('SELECT SUM(COALESCE(cost_usd,0)), SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END), COUNT(*) FROM api_usage WHERE workspace_id=?', (wid,)).fetchone()
        useful = sum((r['feedback'] == 'good' or r['outcome'] in {'qualified', 'purchased'} for r in rows))
        stale = sum((r['analysis_revision'] != core.workspace_revision(ws) or r['analysis_state'] != 'complete' for r in rows))
        return {'funnel': funnel, 'revenue_minor_by_currency': revenue, 'reviewed_useful': useful, 'analysis_stale': stale, 'known_api_cost_usd': round(usage[0] or 0, 6), 'unpriced_api_requests': usage[1] or 0, 'api_cost_per_useful_lead_usd': round((usage[0] or 0) / useful, 6) if useful and usage[2] and (not usage[1]) else None, 'pilot_feedback': core.json_object(ws['pilot_feedback'])}
    finally:
        conn.close()

@core.app.post('/api/workspaces/{wid}/pilot-feedback')
def save_pilot_feedback(wid: int, body: core.PilotFeedback, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    try:
        core.check_ws_owner(conn, wid, user['id'])
        feedback = body.model_dump() | {'recorded_at': core.datetime.now(core.timezone.utc).isoformat()}
        conn.execute('UPDATE workspaces SET pilot_feedback=? WHERE id=?', (core.json.dumps(feedback), wid))
        conn.commit()
        ws = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
    finally:
        conn.close()
    core.sb_sync_workspace_row(dict(ws))
    return {'ok': True}

@core.app.get('/api/admin/pilot')
def pilot_overview(authorization: str=core.Header(None)):
    core.require_admin(authorization)
    conn = core.get_db()
    try:
        cohorts = {name: {'participants': set(), 'would_pay': set(), 'reviewed': 0, 'useful': 0, 'responded': 0, 'purchased': 0} for name in ('founders', 'homemade', 'other')}
        for ws in conn.execute('SELECT * FROM workspaces WHERE user_id != 1'):
            if not core.json_object(ws['pilot_feedback']).get('recorded_at'):
                continue
            kind = core.workspace_profile(ws).get('business_type', '').lower()
            group = 'homemade' if any((word in kind for word in ('homemade', 'd2c'))) else 'founders' if any((word in kind for word in ('saas', 'startup', 'software'))) else 'other'
            bucket = cohorts[group]
            bucket['participants'].add(ws['user_id'])
            if core.json_object(ws['pilot_feedback']).get('would_pay') == 'yes':
                bucket['would_pay'].add(ws['user_id'])
            for lead in conn.execute('SELECT feedback,outcome FROM leads WHERE workspace_id=?', (ws['id'],)):
                bucket['reviewed'] += int(bool(lead['feedback']) or lead['outcome'] != 'new')
                bucket['useful'] += int(lead['feedback'] == 'good' or lead['outcome'] in {'qualified', 'purchased'})
                bucket['responded'] += int(lead['outcome'] in {'responded', 'qualified', 'purchased'})
                bucket['purchased'] += int(lead['outcome'] == 'purchased')
        return {name: dict(values, participants=len(values['participants']), would_pay=len(values['would_pay'])) for name, values in cohorts.items()}
    finally:
        conn.close()

@core.app.post('/api/leads/{lid}/status')
def set_status(lid: int, s: core.Status, authorization: str=core.Header(None)):
    mapping = {'new': 'new', 'replied': 'contacted', 'ignored': 'irrelevant'}
    if s.status not in mapping:
        raise core.HTTPException(400, 'Unknown lead status')
    return core.set_outcome(lid, core.Outcome(stage=mapping[s.status], rejection_reason='Skipped by user' if s.status == 'ignored' else ''), authorization)

@core.app.post('/api/leads/{lid}/feedback')
def set_feedback(lid: int, f: core.Feedback, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    try:
        core.owned_lead(conn, lid, user['id'])
    except Exception:
        conn.close()
        raise
    conn.execute('UPDATE leads SET feedback=? WHERE id=?', (f.feedback, lid))
    conn.commit()
    row = conn.execute('SELECT * FROM leads WHERE id=?', (lid,)).fetchone()
    conn.close()
    if row:
        core.sb_sync_leads_rows([row])
    return {'ok': True, 'feedback': f.feedback}

@core.app.get('/api/plan')
def plan_status(authorization: str=core.Header(None)):
    return core.commerce.plan_status(authorization)

@core.app.post('/api/upgrade-interest')
def upgrade_interest(b: core.Interest, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    now = core.datetime.now(core.timezone.utc).isoformat()
    conn = core.get_db()
    cur = conn.execute('INSERT INTO upgrade_interest(user_id, plan, created_at) VALUES (?,?,?)', (user['id'], b.plan[:30], now))
    iid = cur.lastrowid
    conn.commit()
    conn.close()
    core.sb_rest('POST', 'upgrade_interest', params={'on_conflict': 'id'}, json_body={'id': iid, 'user_id': user['id'], 'plan': b.plan[:30], 'created_at': now}, prefer='resolution=merge-duplicates,return=minimal')
    return {'ok': True}

@core.app.post('/api/admin/plan')
def admin_set_plan(b: core.PlanChange, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    if (user['email'] or '').lower() not in core.ADMIN_EMAILS:
        raise core.HTTPException(403, 'Admins only')
    if b.plan not in core.PLANS:
        raise core.HTTPException(400, f"Unknown plan. Choose one of: {', '.join(core.PLANS)}")
    conn = core.get_db()
    start = core.commerce.now()
    n = conn.execute('UPDATE users SET plan=?,billing_start=?,billing_end=? WHERE email=?', (b.plan, core.commerce.iso(start), core.commerce.iso(core.commerce.next_month(start)), b.email.strip().lower())).rowcount
    conn.commit()
    urow = conn.execute('SELECT * FROM users WHERE email=?', (b.email.strip().lower(),)).fetchone()
    conn.close()
    if not n:
        raise core.HTTPException(404, 'No user with that email')
    if urow:
        core.sb_sync_user_row(dict(urow))
    return {'ok': True, 'email': b.email.strip().lower(), 'plan': b.plan}

@core.app.get('/api/automation/status')
def automation_status(authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    used = core.get_today_quota_used(user_id=user['id'])
    remaining = max(0, core.DAILY_QUOTA_BUDGET - used)
    conn = core.get_db()
    recent_runs = [dict(r) for r in conn.execute('SELECT * FROM runs WHERE user_id=? ORDER BY id DESC LIMIT 5', (user['id'],)).fetchall()]
    conn.close()
    sb_url, sb_key = core.supabase_config()
    email_configured = bool(core.os.getenv('SMTP_HOST') and core.os.getenv('SMTP_USER') and (core.os.getenv('ALERT_EMAIL_TO') or user.get('email')) or core.os.getenv('RESEND_API_KEY') or (sb_url and sb_key))
    tg_configured = bool(core.os.getenv('TELEGRAM_BOT_TOKEN') and core.os.getenv('TELEGRAM_CHAT_ID'))
    return {'scheduler_active': core.scheduler.running, 'interval_hours': 168, 'quota_budget': core.DAILY_QUOTA_BUDGET, 'quota_used_today': used, 'quota_remaining_today': remaining, 'estimated_runs_left_today': remaining // core.ESTIMATED_RUN_QUOTA, 'alerts': {'email_configured': email_configured, 'supabase_email_enabled': bool(sb_url and sb_key), 'telegram_configured': tg_configured, 'recipient_email': user.get('email')}, 'recent_runs': recent_runs}

@core.app.post('/api/automation/trigger')
def trigger_scheduled_now(authorization: str=core.Header(None)):
    core.require_admin(authorization)
    t = core.threading.Thread(target=core.scheduled_auto_run_all, daemon=True)
    t.start()
    return {'ok': True, 'msg': 'Scheduled lead finder triggered in background'}

@core.app.post('/api/alerts/test')
def test_alert(authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    sample_lead = {'author': '@TestBuyer', 'score': 95, 'video_title': 'Best AI Tools 2026', 'video_id': 'test12345', 'comment_id': 'comm12345', 'text': 'Looking for a reliable tool that solves this exact problem!', 'reason': 'Direct buyer inquiry with high purchase intent', 'reply': 'Check out our product, it does exactly this!'}
    res = core.send_lead_alert('Test Product', [sample_lead], recipient_email=user['email'])
    return {'ok': True, 'email_sent': res.get('email', False), 'telegram_sent': res.get('telegram', False), 'recipient': user['email']}

@core.app.post('/api/report')
def report(b: core.Report, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    core.commerce.require_processing(user['id'])
    pool = []
    for v in core.video_ids(b.channel_url.strip()):
        pool += [c for c in core.comments(v, b.per_video) if core.sieve(c)]
    if not pool:
        raise core.HTTPException(400, 'No usable comments found')
    credit, allowed = core.commerce.reserve_analysis(user['id'], min(len(pool), 500))
    pool = pool[:allowed]
    try:
        result = core.gem(core.REPORT_PROMPT.format(channel=b.channel_url, items=core.fmt(pool)))
        if not isinstance(result, dict):
            raise core.HTTPException(502, 'Report response was invalid')
    except Exception:
        core.commerce.settle_analysis(credit, False)
        raise
    else:
        core.commerce.settle_analysis(credit, True)
    verified = []
    for buyer in result.get('buyer_comments', []):
        if not isinstance(buyer, dict) or not isinstance(buyer.get('text'), str) or (not buyer['text'].strip()):
            continue
        source = next((c for c in pool[:500] if buyer['text'] in c['text'] and (not buyer.get('author') or buyer['author'] == c['author'])), None)
        if source:
            verified.append(buyer | {'author': source['author'], 'link': f"https://www.youtube.com/watch?v={source['vid']}&lc={source['id']}", 'published_at': source.get('published_at') or ''})
    result['buyer_comments'] = verified
    return result | {'comments_analysed': len(pool[:500]), 'note': 'Ideas, pricing and purchase intent are hypotheses; validate them with customers.'}
