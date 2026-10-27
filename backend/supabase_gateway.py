"""Supabase Gateway: focused API/service functions."""
from backend import runtime as core

def supabase_config():
    url = (core.os.getenv('SUPABASE_URL') or '').strip().rstrip('/')
    key = (core.os.getenv('SUPABASE_PUBLISHABLE_KEY') or core.os.getenv('SUPABASE_ANON_KEY') or '').strip()
    if key.startswith('sb_secret_'):
        return ('', '')
    if key.startswith('eyJ'):
        try:
            if core.jwt.decode(key, options={'verify_signature': False}).get('role') == 'service_role':
                return ('', '')
        except core.jwt.InvalidTokenError:
            pass
    if url in ('', 'https://your-project-id.supabase.co') or key in ('', 'your_supabase_anon_public_key') or key.startswith('postgresql://'):
        return ('', '')
    return (url, key)

def supabase_service_key():
    sk = (core.os.getenv('SUPABASE_SECRET_KEY') or core.os.getenv('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    ak = (core.os.getenv('SUPABASE_ANON_KEY') or '').strip()
    if sk in ('', 'your_supabase_service_role_key') or sk == ak or sk.startswith('postgresql://'):
        return ''
    return sk

def sb_db_headers(prefer: str='return=representation'):
    _, anon_key = core.supabase_config()
    active_key = core.supabase_service_key()
    if not active_key:
        return {}
    headers = {'apikey': active_key, 'Authorization': f'Bearer {active_key}', 'Content-Type': 'application/json'}
    if prefer:
        headers['Prefer'] = prefer
    return headers

def _sb_request(method: str, url: str, **kwargs):
    if hasattr(core.httpx.request, '_mock_name') or 'MagicMock' in type(core.httpx.request).__name__:
        return core.httpx.request(method, url, **kwargs)
    return core._SB_HTTP_CLIENT.request(method, url, **kwargs)

def _sb_get(url: str, **kwargs):
    if hasattr(core.httpx.get, '_mock_name') or 'MagicMock' in type(core.httpx.get).__name__:
        return core.httpx.get(url, **kwargs)
    return core._SB_HTTP_CLIENT.get(url, **kwargs)

def _sb_post(url: str, **kwargs):
    if hasattr(core.httpx.post, '_mock_name') or 'MagicMock' in type(core.httpx.post).__name__:
        return core.httpx.post(url, **kwargs)
    return core._SB_HTTP_CLIENT.post(url, **kwargs)

def integration_status(provider, status):
    conn = core.get_db()
    try:
        conn.execute('INSERT INTO integration_state(provider,status,checked_at) VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at', (provider, str(status), core.datetime.now(core.timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()

def sb_rest(method: str, table: str, params: dict=None, json_body=None, prefer: str='return=representation'):
    if core.database.is_postgres():
        return []
    sb_url, sb_key = core.supabase_config()
    report = core._SYNC_REPORT.get()
    error = f'{method} {table}: server database credentials are not configured'
    if sb_url and sb_key and core.supabase_service_key():
        for attempt in range(3):
            try:
                response = core._sb_request(method.upper(), f'{sb_url}/rest/v1/{table}', params=params, json=json_body, headers=core.sb_db_headers(prefer=prefer), timeout=10)
                if response.status_code in (200, 201, 204):
                    result = response.json() if response.content else []
                    if report is not None and method.upper() == 'POST':
                        report['pushed'][table] = report['pushed'].get(table, 0) + (len(json_body) if isinstance(json_body, list) else 1)
                    core.integration_status('supabase', 'ok')
                    return result
                error = f'{method} {table}: HTTP {response.status_code}'
                if response.status_code not in (408, 429, 500, 502, 503, 504):
                    break
            except core.httpx.RequestError:
                error = f'{method} {table}: connection error'
            except ValueError:
                error = f'{method} {table}: invalid response'
                break
            if attempt < 2:
                core.time.sleep(0.25 * 2 ** attempt)
    core.integration_status('supabase', error)
    core.logger.warning('Supabase sync failed: %s', error)
    if report is not None:
        report['errors'].append(error)
    return None

def _is_httpx_mocked() -> bool:
    return hasattr(core.httpx.request, '_mock_name') or 'MagicMock' in type(core.httpx.request).__name__ or hasattr(core.httpx.get, '_mock_name') or hasattr(core.httpx.post, '_mock_name')

def _run_sb_async(fn, *args, **kwargs):
    """Run write-through Supabase syncs in a daemon thread in production, or synchronously in unit tests."""
    if core._SYNC_REPORT.get() is not None or core._is_httpx_mocked():
        fn(*args, **kwargs)
    else:
        core.threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()

def sb_sync_user_row(user_row: dict, sync_now: bool=False):
    if not user_row:
        return
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        return
    payload = {'id': int(user_row['id']), 'email': (user_row.get('email') or '').strip().lower(), 'password_hash': user_row.get('password_hash') or '', 'name': user_row.get('name') or '', 'plan': user_row.get('plan') or 'free', 'created_at': user_row.get('created_at') or core.datetime.now(core.timezone.utc).isoformat(), **{key: user_row.get(key) or '' for key in ('billing_start', 'billing_end', 'trial_started_at', 'deleted_at')}, 'email_verified': int(bool(user_row.get('email_verified')))}
    sb_uid = (user_row.get('supabase_uid') or '').strip()
    if sb_uid and core.re.fullmatch('[0-9a-fA-F-]{36}', sb_uid):
        payload['supabase_uid'] = sb_uid
    if sync_now:
        core.sb_rest('POST', 'users', params={'on_conflict': 'email'}, json_body=payload, prefer='resolution=merge-duplicates,return=minimal')
    else:
        core._run_sb_async(core.sb_rest, 'POST', 'users', params={'on_conflict': 'email'}, json_body=payload, prefer='resolution=merge-duplicates,return=minimal')

def sb_sync_workspace_row(ws_row: dict, sync_now: bool=False):
    if not ws_row:
        return
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        return
    payload = {'id': int(ws_row['id']), 'user_id': int(ws_row.get('user_id') or 1), 'name': ws_row.get('name') or '', 'pitch': ws_row.get('pitch') or '', 'signals': ws_row.get('signals') or '', 'rules': ws_row.get('rules') or 'No links. No emojis spam.', 'blocklist': ws_row.get('blocklist') or '', 'profile': core.workspace_profile(ws_row), 'pilot_feedback': core.json_object(ws_row.get('pilot_feedback'))}
    if sync_now:
        core.sb_rest('POST', 'workspaces', params={'on_conflict': 'id'}, json_body=payload, prefer='resolution=merge-duplicates,return=minimal')
    else:
        core._run_sb_async(core.sb_rest, 'POST', 'workspaces', params={'on_conflict': 'id'}, json_body=payload, prefer='resolution=merge-duplicates,return=minimal')

def lead_sync_payload(row):
    d = dict(row)
    return {'id': int(d['id']), 'workspace_id': int(d['workspace_id']), 'comment_id': str(d.get('comment_id') or ''), 'video_id': str(d.get('video_id') or ''), 'video_title': str(d.get('video_title') or ''), 'author': str(d.get('author') or ''), 'text': str(d.get('text') or ''), 'score': int(d.get('score') or 0), 'reason': str(d.get('reason') or ''), 'reply': str(d.get('reply') or ''), 'status': str(d.get('status') or 'new'), 'feedback': str(d.get('feedback') or ''), 'channel_title': str(d.get('channel_title') or ''), 'channel_id': str(d.get('channel_id') or ''), 'unlocked': int(d.get('unlocked') or 0), **{key: d.get(key) or '' for key in ('published_at', 'source_updated_at', 'buyer_type', 'analysis_revision', 'analysis_state', 'outcome', 'currency', 'rejection_reason', 'outcome_updated_at', 'retrieved_at')}, 'revenue_minor': int(d.get('revenue_minor') or 0), 'retention_expired': int(bool(d.get('retention_expired'))), 'evidence': core.json_object(d.get('evidence'))}

def sb_sync_leads_rows(lead_rows: list, sync_now: bool=False):
    if not lead_rows:
        return
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        return
    ids = [int(row['id']) for row in lead_rows]

    def _push_batches():
        with core.commerce.LIFECYCLE_LOCK:
            for i in range(0, len(ids), 100):
                selected = ids[i:i + 100]
                conn = core.get_db()
                try:
                    rows = conn.execute('SELECT l.* FROM leads l JOIN workspaces w ON w.id=l.workspace_id WHERE l.id IN (' + ','.join(('?' for _ in selected)) + ") AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.user_id=w.user_id AND d.status!='done')", selected).fetchall()
                finally:
                    conn.close()
                batch = [core.lead_sync_payload(row) for row in rows if not row['retention_expired']]
                if batch:
                    core.sb_rest('POST', 'leads', params={'on_conflict': 'workspace_id,comment_id'}, json_body=batch, prefer='resolution=merge-duplicates,return=minimal')
    if sync_now:
        _push_batches()
    else:
        core._run_sb_async(_push_batches)

def sb_sync_job_row(jid: int):
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key or (not jid):
        return
    conn = core.get_db()
    row = conn.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        core._run_sb_async(core.sb_rest, 'POST', 'jobs', params={'on_conflict': 'id'}, json_body=d, prefer='resolution=merge-duplicates,return=minimal')

def sb_sync_run_row(run_id: int):
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key or (not run_id):
        return
    conn = core.get_db()
    row = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        core._run_sb_async(core.sb_rest, 'POST', 'runs', params={'on_conflict': 'id'}, json_body=d, prefer='resolution=merge-duplicates,return=minimal')

def sync_all_to_supabase() -> dict:
    if core.database.is_postgres():
        return {'ok': True, 'mode': 'authoritative', 'message': 'All application data already resides in Supabase Postgres'}
    if not core.supabase_service_key():
        return {'ok': False, 'error': 'SUPABASE_SERVICE_ROLE_KEY is required for database sync'}
    report = {'errors': [], 'pushed': {}}
    token = core._SYNC_REPORT.set(report)
    try:
        result = core._sync_all_to_supabase()
        if not result['ok']:
            return result
        result['pushed'] = {key: report['pushed'].get(table, 0) for key, table in (('users', 'users'), ('workspaces', 'workspaces'), ('leads', 'leads'), ('jobs', 'jobs'), ('runs', 'runs'), ('emails', 'email_logs'))}
        result['errors'] = report['errors']
        result['ok'] = not report['errors']
        if report['errors']:
            result['error'] = 'Supabase sync incomplete: ' + '; '.join(report['errors'])
        return result
    finally:
        core._SYNC_REPORT.reset(token)

def _sync_all_to_supabase() -> dict:
    """Push all local SQLite data to Supabase Postgres tables and pull remote workspaces/leads."""
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        return {'ok': False, 'error': 'Supabase URL and Key are not configured'}
    conn = core.get_db()
    users = [dict(r) for r in conn.execute("SELECT * FROM users WHERE COALESCE(deleted_at,'')=''").fetchall()]
    workspaces = [dict(r) for r in conn.execute('SELECT * FROM workspaces').fetchall()]
    leads_rows = [dict(r) for r in conn.execute('SELECT * FROM leads').fetchall()]
    jobs_rows = [dict(r) for r in conn.execute('SELECT * FROM jobs').fetchall()]
    runs_rows = [dict(r) for r in conn.execute('SELECT * FROM runs').fetchall()]
    interest_rows = [dict(r) for r in conn.execute('SELECT * FROM upgrade_interest').fetchall()]
    email_rows = [dict(r) for r in conn.execute('SELECT * FROM email_logs').fetchall()]
    conn.close()
    for u in users:
        core.sb_sync_user_row(u, sync_now=True)
    for w in workspaces:
        core.sb_sync_workspace_row(w, sync_now=True)
    if leads_rows:
        core.sb_sync_leads_rows(leads_rows, sync_now=True)
    for j in jobs_rows[-50:]:
        core.sb_rest('POST', 'jobs', params={'on_conflict': 'id'}, json_body=j, prefer='resolution=merge-duplicates,return=minimal')
    for rn in runs_rows[-50:]:
        core.sb_rest('POST', 'runs', params={'on_conflict': 'id'}, json_body=rn, prefer='resolution=merge-duplicates,return=minimal')
    for it in interest_rows:
        core.sb_rest('POST', 'upgrade_interest', params={'on_conflict': 'id'}, json_body=it, prefer='resolution=merge-duplicates,return=minimal')
    for em in email_rows[-50:]:
        core.sb_rest('POST', 'email_logs', params={'on_conflict': 'id'}, json_body=em, prefer='resolution=merge-duplicates,return=minimal')
    pulled_ws, pulled_leads = (0, 0)
    rem_ws = core.sb_rest('GET', 'workspaces', params={'select': '*', 'order': 'id.asc'})
    if isinstance(rem_ws, list):
        conn = core.get_db()
        for rw in rem_ws:
            exists = conn.execute('SELECT id FROM workspaces WHERE id=?', (rw['id'],)).fetchone()
            if not exists and rw.get('name'):
                conn.execute('INSERT OR IGNORE INTO workspaces(id, user_id, name, pitch, signals, rules, blocklist, profile, pilot_feedback) VALUES (?,?,?,?,?,?,?,?,?)', (rw['id'], rw.get('user_id') or 1, rw.get('name'), rw.get('pitch') or '', rw.get('signals') or '', rw.get('rules') or '', rw.get('blocklist') or '', core.json.dumps(core.workspace_profile(rw), ensure_ascii=False), core.json.dumps(core.json_object(rw.get('pilot_feedback')))))
                pulled_ws += 1
        conn.commit()
        conn.close()
    rem_leads = core.sb_rest('GET', 'leads', params={'select': '*', 'score': 'gte.40', 'limit': '500'})
    if isinstance(rem_leads, list):
        conn = core.get_db()
        for rl in rem_leads:
            cur = conn.execute('INSERT OR IGNORE INTO leads(workspace_id, comment_id, video_id, video_title, author, text, score, reason, reply, status, feedback, channel_title, channel_id, unlocked) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (rl.get('workspace_id'), rl.get('comment_id'), rl.get('video_id') or '', rl.get('video_title') or '', rl.get('author') or '', rl.get('text') or '', rl.get('score') or 0, rl.get('reason') or '', rl.get('reply') or '', rl.get('status') or 'new', rl.get('feedback') or '', rl.get('channel_title') or '', rl.get('channel_id') or '', rl.get('unlocked') or 0))
            if cur.rowcount:
                extra_keys = ('published_at', 'source_updated_at', 'buyer_type', 'analysis_revision', 'analysis_state', 'outcome', 'revenue_minor', 'currency', 'rejection_reason', 'outcome_updated_at')
                restored = {key: rl[key] for key in extra_keys if key in rl and rl[key] is not None}
                restored['evidence'] = core.json.dumps(core.json_object(rl.get('evidence')), ensure_ascii=False)
                conn.execute('UPDATE leads SET ' + ','.join((key + '=?' for key in restored)) + ' WHERE workspace_id=? AND comment_id=?', [*restored.values(), rl.get('workspace_id'), rl.get('comment_id')])
                pulled_leads += 1
        conn.commit()
        conn.close()
    return {'ok': True, 'pushed': {'users': len(users), 'workspaces': len(workspaces), 'leads': len(leads_rows), 'jobs': len(jobs_rows[-50:]), 'runs': len(runs_rows[-50:]), 'emails': len(email_rows[-50:])}, 'pulled': {'workspaces': pulled_ws, 'leads': pulled_leads}}
