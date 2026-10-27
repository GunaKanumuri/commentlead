"""Lifecycle service."""
from backend import commercial as core

def source_visible(row):
    d = dict(row)
    if d.get('retention_expired'):
        return False
    if core.os.getenv('APP_ENV') != 'production':
        return True
    stamp = core.parse(d.get('retrieved_at'))
    return bool(stamp and stamp >= core.now() - core.timedelta(days=30))

def queue_source_sync(conn, lead_id):
    conn.execute("INSERT INTO lifecycle_sync VALUES(?,?,'') ON CONFLICT(lead_id) DO UPDATE SET updated_at=excluded.updated_at,error=''", (lead_id, core.iso(core.now())))

def expire_source(conn, row):
    token = 'expired:' + core.identity_hash('comment:' + row['comment_id'])
    conn.execute("UPDATE leads SET comment_id=?,video_id='',text='',author='',video_title='',channel_title='',channel_id='',\n        published_at='',source_updated_at='',score=0,buyer_type='unknown',analysis_revision='',reason='',reply='',evidence='{}',\n        retention_expired=1,analysis_state='expired' WHERE id=?", (token, row['id']))
    core.queue_source_sync(conn, row['id'])

def flush_source_sync(limit=200):
    with core.LIFECYCLE_LOCK:
        url, key = core.R['supabase_config']()
        conn = core.R['get_db']()
        try:
            pending = [dict(r) for r in conn.execute('SELECT * FROM lifecycle_sync ORDER BY updated_at LIMIT ?', (limit,))]
        finally:
            conn.close()
        completed = 0
        conn = core.R['get_db']()
        try:
            alert_task = conn.execute("SELECT updated_at FROM lifecycle_cleanup_tasks WHERE task='alert_logs'").fetchone()
        finally:
            conn.close()
        if alert_task:
            error = ''
            if url and key:
                try:
                    result = core.R['sb_rest']('PATCH', 'email_logs', params={'email_type': 'eq.lead_alert'}, json_body={'body': core.ALERT_LOG_BODY}, prefer='return=minimal')
                    if result is None:
                        error = 'Alert log mirror cleanup failed; retry pending'
                except Exception:
                    error = 'Alert log mirror unavailable; retry pending'
            conn = core.R['get_db']()
            try:
                if error:
                    conn.execute("UPDATE lifecycle_cleanup_tasks SET error=? WHERE task='alert_logs'", (error,))
                else:
                    conn.execute("DELETE FROM lifecycle_cleanup_tasks WHERE task='alert_logs' AND updated_at=?", (alert_task[0],))
                conn.commit()
            finally:
                conn.close()
        for item in pending:
            conn = core.R['get_db']()
            try:
                row = conn.execute('SELECT * FROM leads WHERE id=?', (item['lead_id'],)).fetchone()
            finally:
                conn.close()
            error = ''
            if row and url and key:
                try:
                    result = core.R['sb_rest']('PATCH', 'leads', params={'id': 'eq.' + str(row['id'])}, json_body=core.R['lead_sync_payload'](row), prefer='return=minimal')
                    if result is None:
                        error = 'Source mirror update failed; retry pending'
                except Exception:
                    error = 'Source mirror unavailable; retry pending'
            conn = core.R['get_db']()
            try:
                if error:
                    conn.execute('UPDATE lifecycle_sync SET error=? WHERE lead_id=?', (error, item['lead_id']))
                else:
                    conn.execute('DELETE FROM lifecycle_sync WHERE lead_id=? AND updated_at=?', (item['lead_id'], item['updated_at']))
                    completed += 1
                conn.commit()
            finally:
                conn.close()
        return completed

def refresh_sources(limit=200):
    conn = core.R['get_db']()
    try:
        if conn.execute("UPDATE email_logs SET body=? WHERE email_type='lead_alert' AND body!=?", (core.ALERT_LOG_BODY, core.ALERT_LOG_BODY)).rowcount:
            conn.execute("INSERT OR REPLACE INTO lifecycle_cleanup_tasks VALUES('alert_logs',?,'')", (core.iso(core.now()),))
        conn.commit()
        rows = [dict(row) for row in conn.execute("SELECT * FROM leads WHERE retention_expired=0 AND (COALESCE(retrieved_at,'')='' OR retrieved_at<?) ORDER BY retrieved_at LIMIT ?", (core.iso(core.now() - core.timedelta(days=21)), limit))]
    finally:
        conn.close()
    refreshed = []
    failed = 0
    context = core.R['_API_CONTEXT'].set({'maintenance': True})
    try:
        for offset in range(0, len(rows), 50):
            batch = rows[offset:offset + 50]
            try:
                result = core.R['yt']('comments', part='snippet', id=','.join((row['comment_id'] for row in batch)))
                source = {item['id']: item.get('snippet', {}) for item in result.get('items', [])}
                video_ids = list({row['video_id'] for row in batch if row['comment_id'] in source})
                video_info = {}
                if video_ids:
                    videos = core.R['yt']('videos', part='snippet', id=','.join(video_ids))
                    video_info = {item['id']: item.get('snippet', {}) for item in videos.get('items', [])}
            except Exception:
                failed += len(batch)
                continue
            conn = core.R['get_db']()
            try:
                for row in batch:
                    snippet = source.get(row['comment_id'])
                    video = video_info.get(row['video_id'])
                    if not snippet or not video:
                        core.expire_source(conn, row)
                    else:
                        text = snippet.get('textOriginal') or snippet.get('textDisplay') or ''
                        changed = text != row['text']
                        conn.execute("UPDATE leads SET text=?,author=?,video_title=?,channel_title=?,channel_id=?,published_at=?,source_updated_at=?,retrieved_at=?,retention_expired=0,\n                            analysis_state=CASE WHEN ? THEN 'pending' ELSE analysis_state END WHERE id=?", (text, snippet.get('authorDisplayName', ''), video.get('title', ''), video.get('channelTitle', ''), video.get('channelId', ''), core.R['source_date'](snippet.get('publishedAt')), core.R['source_date'](snippet.get('updatedAt')), core.iso(core.now()), changed, row['id']))
                        if changed:
                            conn.execute("UPDATE leads SET score=0,reason='',reply='',evidence='{}',analysis_revision='' WHERE id=?", (row['id'],))
                        core.queue_source_sync(conn, row['id'])
                    refreshed.append(row['id'])
                conn.commit()
            finally:
                conn.close()
    finally:
        core.R['_API_CONTEXT'].reset(context)
    cutoff = core.iso(core.now() - core.timedelta(days=22))
    conn = core.R['get_db']()
    try:
        expired = conn.execute("SELECT * FROM leads WHERE retention_expired=0 AND (COALESCE(retrieved_at,'')='' OR retrieved_at<?)", (cutoff,)).fetchall()
        if expired:
            for row in expired:
                core.expire_source(conn, row)
            conn.commit()
    finally:
        conn.close()
    flushed = core.flush_source_sync()
    return {'refreshed_or_removed': len(refreshed), 'refresh_failures': failed, 'expired_removed': len(expired), 'mirror_updates_completed': flushed}

def process_deletions():
    with core.LIFECYCLE_LOCK:
        return core._process_deletions()

def _process_deletions():
    if not core.R.get('_COMMERCIAL_READY'):
        return
    conn = core.R['get_db']()
    try:
        requests = [dict(row) for row in conn.execute("SELECT * FROM deletion_requests WHERE status!='done' LIMIT 10")]
    finally:
        conn.close()
    for request in requests:
        uid = request['user_id']
        conn = core.R['get_db']()
        try:
            user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            if not user:
                continue
            conn.execute("UPDATE jobs SET status='interrupted',payload='',msg='Account deletion requested' WHERE user_id=? AND status='queued'", (uid,))
            conn.commit()
            if conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='running'", (uid,)).fetchone()[0]:
                continue
            workspaces = [row[0] for row in conn.execute('SELECT id FROM workspaces WHERE user_id=?', (uid,))]
        finally:
            conn.close()
        try:
            url, key = core.R['supabase_config']()
            if url and key:
                if not core.R['supabase_service_key']():
                    raise RuntimeError('Server sync credential required for remote deletion')
                for wid in workspaces:
                    if core.R['sb_rest']('DELETE', 'leads', params={'workspace_id': 'eq.' + str(wid)}) is None:
                        raise RuntimeError('Remote lead deletion failed')
                for table in ('jobs', 'runs', 'upgrade_interest', 'email_logs', 'workspaces'):
                    if core.R['sb_rest']('DELETE', table, params={'user_id': 'eq.' + str(uid)}) is None:
                        raise RuntimeError('Remote deletion failed: ' + table)
                if core.R['sb_rest']('DELETE', 'users', params={'id': 'eq.' + str(uid)}) is None:
                    raise RuntimeError('Remote user deletion failed')
                if user['supabase_uid']:
                    response = core.R['_sb_request']('DELETE', url + '/auth/v1/admin/users/' + user['supabase_uid'], headers=core.R['sb_db_headers'](), timeout=15)
                    if response.status_code not in (200, 204, 404):
                        raise RuntimeError('Cloud identity deletion failed')
            conn = core.R['get_db']()
            try:
                conn.execute('BEGIN IMMEDIATE')
                for wid in workspaces:
                    conn.execute('DELETE FROM lead_outcome_events WHERE lead_id IN (SELECT id FROM leads WHERE workspace_id=?)', (wid,))
                    conn.execute('DELETE FROM match_grants WHERE lead_id IN (SELECT id FROM leads WHERE workspace_id=?)', (wid,))
                    conn.execute('DELETE FROM leads WHERE workspace_id=?', (wid,))
                for table in ('api_usage', 'analysis_credits', 'jobs', 'runs', 'upgrade_interest', 'email_logs', 'workspaces', 'policy_acceptance', 'billing_subscriptions'):
                    conn.execute('DELETE FROM ' + table + ' WHERE user_id=?', (uid,))
                conn.execute("UPDATE users SET email=?,password_hash='',name='',supabase_uid='',plan='free',billing_start='',billing_end='',email_verified=0,deleted_at=? WHERE id=?", ('deleted-' + core.secrets.token_hex(16) + '@deleted.invalid', core.iso(core.now()), uid))
                conn.execute("UPDATE deletion_requests SET status='done',error='' WHERE user_id=?", (uid,))
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            conn = core.R['get_db']()
            try:
                conn.execute("UPDATE deletion_requests SET status='retry',error=? WHERE user_id=?", (str(exc)[:200], uid))
                conn.commit()
            finally:
                conn.close()

def policy_page(kind):
    from html import escape
    operator = core.os.getenv('OPERATOR_NAME') or 'Comment → Money (operator details pending)'
    contact = core.os.getenv('SUPPORT_EMAIL') or 'Contact address must be configured before launch'
    paragraphs = {'privacy': ['We use YouTube API Services to retrieve public comment text, display names, source links and source dates. We do not request your YouTube password or post replies automatically.', 'We store your account, product profile, outcome records and essential authentication/trial-abuse controls. Trial controls use a signed browser cookie and keyed hashes of email aliases and request addresses, not invasive device fingerprinting.', 'Public source data is refreshed or removed within 30 days. User-provided product and conversation outcome information is kept while your account is active. Source data and its AI classifications may be sent to the configured Google Gemini service for analysis; operators must configure an appropriate commercial data-processing tier.', 'Use account deletion to request removal from the Supabase application database and authentication service. Pending requests disable account access and are retried if a remote service fails. Deletion must be completed within seven days; the operator must monitor pending failures. Minimal anti-abuse hashes may be retained for up to 180 days. Operator-managed backups must follow the same deletion and retention requirements.', 'Google services have their own privacy terms: <a href="https://policies.google.com/privacy">Google Privacy Policy</a>. Contact the operator to request access, correction or deletion, including data about a public comment author.'], 'terms': ['This service assists manual customer discovery. Matching scores are product estimates, not YouTube metrics or verified purchase intent. Match allowances are maximums; relevant people, replies and sales are never guaranteed.', 'Use of this service also binds you to the <a href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>. Do not spam, harass, collect private contact information or use additional accounts to bypass a trial or allowance.', 'The trial is one seven-day period with up to 30 matched opportunities and 150 analysed comments. Starter costs INR 499 per billing month: one product, up to 200 matches, 2,000 analysed comments and five discovery runs. Boost costs INR 999 per billing month: two products sharing up to 1,000 matches, 8,000 analysed comments and ten discovery runs. Reassessment consumes analysis allowance. New match allowances renew only for a paid billing period; unused allowance does not roll over.', 'Discovery is queued and subject to shared provider capacity. Weekly scheduled searches, where included, consume the same monthly allowance. Historical results may be removed or refreshed under source-data retention rules. You retain control over whether to contact anyone.', 'Subscriptions renew through the configured provider until cancelled. Use cancellation to stop future renewals at the end of the paid period. Provider checkout controls currency, supported payment methods and any disclosed taxes. The operator must publish any additional taxes before checkout.'], 'refunds': ['Contact the operator with your subscription reference to request review of a duplicate charge, billing error or service failure. Requests are reviewed individually; submitting a request is not an automatic refund.', 'Cancellation stops future renewal at the end of the paid period; it does not automatically refund earlier charges. Statutory consumer rights remain applicable. The operator must confirm its final refund policy, legal identity and customer-support process before enabling payments.']}
    paragraphs['privacy'].append('If you join the launch waitlist, we store your email, optional name, requested feature, referral source and consent date in Supabase. No account or password is created. We use these details for launch updates only. Contact the operator to request removal.')
    paragraphs['privacy'].append('We count homepage requests and preview outcomes using daily pseudonymous browser identifiers. These usage counters contain no searches, comment text, email addresses or raw IP addresses. They are removed after 90 days on the next tracked request. Homepage counts may include automated traffic.')
    if core.R['waitlist_mode']() and kind=='terms':
        paragraphs['terms']=paragraphs['terms'][:2]+['The public comment preview is free and does not require an account. Product matching, reply drafts, saved leads and automated searches are not publicly available yet. Joining their waitlist is not a purchase, subscription or promise of access. No payment is collected.']
    body = ''.join(('<p>' + text + '</p>' for text in paragraphs[kind]))
    draft = not (core.os.getenv('OPERATOR_NAME') and core.os.getenv('SUPPORT_EMAIL'))
    return core.HTMLResponse('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + kind.title() + '</title><body style="font:17px system-ui;line-height:1.6;max-width:780px;margin:40px auto;padding:20px"><nav><a href="/">Home</a> · <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · <a href="/refunds">Refunds</a></nav><h1>' + kind.title() + '</h1><p>' + ('Draft — complete operator details before launch. ' if draft else '') + 'Version ' + core.POLICY_VERSION + '</p><p>Operator: ' + escape(operator) + '<br>Contact: ' + escape(contact) + '</p>' + body + '</body></html>')

def install_lifecycle(runtime):
    app = runtime['app']

    @app.post('/api/legal/accept-public')
    def public_accept(body: core.Consent):
        if not body.accepted or body.version != core.POLICY_VERSION:
            raise core.HTTPException(400, 'Accept the current policies')
        return core.consent_response()

    @app.get('/terms', response_class=core.HTMLResponse)
    def terms():
        return core.policy_page('terms')

    @app.get('/privacy', response_class=core.HTMLResponse)
    def privacy():
        return core.policy_page('privacy')

    @app.get('/refunds', response_class=core.HTMLResponse)
    def refunds():
        return core.policy_page('refunds')

    @app.post('/api/account/delete', status_code=202)
    def delete_account(body: core.DeleteAccount, authorization: str=core.Header(None)):
        user = core.R['get_current_user'](authorization)
        conn = core.R['get_db']()
        try:
            sub = conn.execute("SELECT id FROM billing_subscriptions WHERE user_id=? AND status IN ('active','authenticated','pending','created')", (user['id'],)).fetchone()
        finally:
            conn.close()
        if sub:
            core.gateway('POST', 'subscriptions/' + sub['id'] + '/cancel', {'cancel_at_cycle_end': 1})
        conn = core.R['get_db']()
        try:
            conn.execute("INSERT INTO deletion_requests(user_id,requested_at,status) VALUES(?,?,'pending') ON CONFLICT(user_id) DO UPDATE SET status='pending'", (user['id'], core.iso(core.now())))
            conn.commit()
        finally:
            conn.close()
        return {'ok': True, 'status': 'pending', 'message': 'Account access is disabled. Deletion will be processed and monitored; contact support if it is not completed within seven days.'}

    @app.post('/api/admin/retention')
    def refresh(authorization: str=core.Header(None)):
        core.R['require_admin'](authorization)
        return core.refresh_sources()

    @app.get('/api/admin/readiness')
    def readiness(authorization: str=core.Header(None)):
        core.R['require_admin'](authorization)
        conn = core.R['get_db']()
        try:
            pending = conn.execute("SELECT COUNT(*) FROM deletion_requests WHERE status!='done'").fetchone()[0]
            legacy = conn.execute("SELECT COUNT(*) FROM leads WHERE COALESCE(retrieved_at,'')='' AND retention_expired=0").fetchone()[0]
            mirror_pending = conn.execute('SELECT COUNT(*) FROM lifecycle_sync').fetchone()[0]
            mirror_pending += conn.execute('SELECT COUNT(*) FROM lifecycle_cleanup_tasks').fetchone()[0]
        finally:
            conn.close()
        return {'youtube_approval_recorded': core.os.getenv('YOUTUBE_USE_CASE_APPROVED') == 'true', 'service_key_configured': bool(core.R['supabase_service_key']()), 'operator_details_configured': bool(core.os.getenv('OPERATOR_NAME') and core.os.getenv('SUPPORT_EMAIL')), 'pending_deletions': pending, 'legacy_sources_needing_refresh': legacy, 'pending_source_mirror_updates': mirror_pending, 'payments_configured': bool(core.os.getenv('RAZORPAY_KEY_ID') and core.os.getenv('RAZORPAY_KEY_SECRET') and core.os.getenv('RAZORPAY_WEBHOOK_SECRET'))}

def database_backup():
    if core.R.get('database') and core.R['database'].is_postgres():
        raise RuntimeError('Use Supabase database backups or pg_dump; local SQLite snapshots are no longer used')
    from pathlib import Path
    path = Path(core.R['DB_PATH']).resolve()
    directory = path.parent / '.app-backups'
    directory.mkdir(exist_ok=True)
    target = directory / ('app-snapshot-' + core.now().strftime('%Y%m%dT%H%M%S%fZ') + '.db')
    conn = core.R['get_db']()
    import sqlite3
    backup = sqlite3.connect(target)
    try:
        conn.backup(backup)
    finally:
        backup.close()
        conn.close()
    for candidate in directory.glob('app-snapshot-*.db'):
        resolved = candidate.resolve()
        if resolved.parent == directory.resolve() and resolved.stat().st_mtime < core.now().timestamp() - 6 * 86400:
            resolved.unlink()
    return str(target)

def production_preflight():
    if core.os.getenv('APP_ENV') != 'production':
        return
    missing = []
    for key in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPPORT_EMAIL', 'OPERATOR_NAME', 'APP_URL'):
        if not core.os.getenv(key):
            missing.append(key)
    if not core.R.get('_configured_jwt_secret'):
        missing.append('stable private JWT_SECRET')
    if '*' in core.R.get('ALLOWED_ORIGINS', []):
        missing.append('restricted ALLOWED_ORIGINS')
    if core.R.get('database') and core.R['database'].is_postgres() and (not (core.os.getenv('SUPABASE_DB_URL') or core.os.getenv('DATABASE_URL'))):
        missing.append('SUPABASE_DB_URL')
    if not core.os.getenv('APP_URL', '').startswith('https://'):
        missing.append('HTTPS APP_URL')
    if core.os.getenv('JOB_EXECUTION_MODE', 'queued') != 'queued':
        missing.append('queued production execution')
    if core.os.getenv('RENDER') == 'true' and (not core.R['database'].is_postgres()):
        from pathlib import Path
        mount = Path(core.os.getenv('PERSISTENT_DISK_PATH', '/var/data')).resolve()
        database = Path(core.R['DB_PATH']).resolve()
        if not mount.is_dir() or not core.os.path.ismount(mount):
            missing.append('mounted persistent disk')
        if not database.is_relative_to(mount):
            missing.append('DB_PATH beneath persistent disk')
    if missing:
        raise RuntimeError('Production configuration incomplete: ' + ', '.join(missing))

def consent_response():
    response = core.JSONResponse({'ok': True})
    response.set_cookie('cm_policy', core.POLICY_VERSION + '.' + core.identity_hash('consent:' + core.POLICY_VERSION), httponly=True, secure=core.os.getenv('APP_ENV') == 'production', samesite='lax', max_age=31536000)
    return response
