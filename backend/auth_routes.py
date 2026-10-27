"""Auth Routes: focused API/service functions."""
from backend import runtime as core

@core.app.get('/api/auth/config')
def get_auth_config():
    sb_url, sb_key = core.supabase_config()
    srv_key = core.supabase_service_key()
    return {'supabase_enabled': bool(sb_url and sb_key), 'supabase_url': sb_url, 'supabase_anon_key': sb_key, 'auth_provider': 'supabase', 'storage': 'supabase-postgres' if core.database.is_postgres() else 'isolated-test-database'}

@core.app.post('/api/auth/supabase-config')
def save_supabase_config(b: core.SupabaseConfigUpdate, authorization: str=core.Header(None)):
    core.require_admin(authorization)
    url = (b.supabase_url or '').strip().rstrip('/')
    key = (b.supabase_anon_key or '').strip()
    srv_key = (b.supabase_service_role_key or '').strip()
    if not core.re.fullmatch('https://[a-z0-9-]+\\.supabase\\.co', url):
        raise core.HTTPException(400, 'Please enter a valid Supabase Project URL (e.g. https://xyz.supabase.co)')
    if len(key) < 20:
        raise core.HTTPException(400, 'Please enter a valid Supabase Anon Public Key')
    core.os.environ['SUPABASE_URL'] = url
    core.os.environ['SUPABASE_ANON_KEY'] = key
    if srv_key:
        core.os.environ['SUPABASE_SERVICE_ROLE_KEY'] = srv_key
    try:
        env_path = '.env'
        txt = open(env_path, 'r', encoding='utf-8').read() if core.os.path.exists(env_path) else ''
        if 'SUPABASE_URL=' in txt:
            txt = core.re.sub('^SUPABASE_URL=.*$', f'SUPABASE_URL={url}', txt, flags=core.re.M)
        else:
            txt += f'\nSUPABASE_URL={url}\n'
        if 'SUPABASE_ANON_KEY=' in txt:
            txt = core.re.sub('^SUPABASE_ANON_KEY=.*$', f'SUPABASE_ANON_KEY={key}', txt, flags=core.re.M)
        else:
            txt += f'SUPABASE_ANON_KEY={key}\n'
        if srv_key:
            if 'SUPABASE_SERVICE_ROLE_KEY=' in txt:
                txt = core.re.sub('^SUPABASE_SERVICE_ROLE_KEY=.*$', f'SUPABASE_SERVICE_ROLE_KEY={srv_key}', txt, flags=core.re.M)
            else:
                txt += f'SUPABASE_SERVICE_ROLE_KEY={srv_key}\n'
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(txt)
    except Exception:
        pass
    core.threading.Thread(target=core.sync_all_to_supabase, daemon=True).start()
    return {'ok': True, 'supabase_enabled': True, 'supabase_url': url, 'supabase_anon_key': key, 'service_role_configured': bool(srv_key or core.supabase_service_key())}

@core.app.post('/api/auth/magic-link')
def send_magic_link_email(b: core.EmailAction):
    email = (b.email or '').strip().lower()
    if not email or '@' not in email:
        raise core.HTTPException(400, 'Please enter a valid email address')
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        raise core.HTTPException(400, 'Connect your Supabase URL & Anon Key first to send Supabase Magic Link emails')
    try:
        r = core._sb_post(f'{sb_url}/auth/v1/otp', params={'redirect_to': core.os.getenv('FRONTEND_URL', 'http://localhost:3000')}, headers={'apikey': sb_key, 'Content-Type': 'application/json'}, json={'email': email, 'create_user': True}, timeout=15)
    except core.httpx.RequestError as e:
        raise core.HTTPException(503, f'Supabase connection error: {e}')
    if r.status_code not in (200, 201, 204):
        data = r.json() if r.content else {}
        msg = data.get('msg') or data.get('error_description') or data.get('message') or 'Could not send Supabase Magic Link email'
        raise core.HTTPException(400, msg)
    core.record_email_log(email, '🔑 Your Comment → Money Magic Login Link', f'Supabase Auth Magic Link / OTP sent to {email}', email_type='magic_link', provider='supabase_auth', status='sent')
    return {'ok': True, 'msg': f'✓ Magic login link sent to {email} via Supabase Auth! Check your inbox.'}

@core.app.post('/api/auth/forgot-password')
def send_password_reset_email(b: core.EmailAction):
    email = (b.email or '').strip().lower()
    if not email or '@' not in email:
        raise core.HTTPException(400, 'Please enter your email address first')
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        raise core.HTTPException(400, 'Connect your Supabase URL & Anon Key first to send password reset emails')
    try:
        r = core._sb_post(f'{sb_url}/auth/v1/recover', params={'redirect_to': core.os.getenv('FRONTEND_URL', 'http://localhost:3000')}, headers={'apikey': sb_key, 'Content-Type': 'application/json'}, json={'email': email}, timeout=15)
    except core.httpx.RequestError as e:
        raise core.HTTPException(503, f'Supabase connection error: {e}')
    if r.status_code not in (200, 201, 204):
        data = r.json() if r.content else {}
        msg = data.get('msg') or data.get('error_description') or data.get('message') or 'Could not send password recovery email'
        raise core.HTTPException(400, msg)
    core.record_email_log(email, '🔒 Reset your Comment → Money password', f'Supabase Auth Password Reset email sent to {email}', email_type='password_reset', provider='supabase_auth', status='sent')
    return {'ok': True, 'msg': f'✓ Password reset email sent to {email} via Supabase Auth!'}

@core.app.post('/api/auth/resend-confirmation')
def resend_confirmation_email(b: core.EmailAction):
    email = (b.email or '').strip().lower()
    if not email or '@' not in email:
        raise core.HTTPException(400, 'Please enter a valid email address')
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        raise core.HTTPException(400, 'Connect your Supabase URL & Anon Key first')
    try:
        r = core._sb_post(f'{sb_url}/auth/v1/resend', headers={'apikey': sb_key, 'Content-Type': 'application/json'}, json={'type': 'signup', 'email': email}, timeout=15)
    except core.httpx.RequestError as e:
        raise core.HTTPException(503, f'Supabase connection error: {e}')
    if r.status_code not in (200,201,204):raise core.HTTPException(400,'Could not send the confirmation email. Please retry later.')
    core.record_email_log(email, '✉ Confirm your Comment → Money account', f'Supabase Auth Signup Confirmation email resent to {email}', email_type='signup_confirm', provider='supabase_auth', status='sent')
    return {'ok': True, 'msg': f'✓ Confirmation email resent to {email} via Supabase Auth!'}

@core.app.get('/api/supabase/status')
def supabase_status(authorization: str=core.Header(None)):
    core.require_admin(authorization)
    sb_url, sb_key = core.supabase_config()
    srv_key = core.supabase_service_key()
    conn = core.get_db()
    local_counts = {'users': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 'workspaces': conn.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0], 'leads': conn.execute('SELECT COUNT(*) FROM leads WHERE score>=40').fetchone()[0], 'jobs': conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 'runs': conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 'emails': conn.execute('SELECT COUNT(*) FROM email_logs').fetchone()[0]}
    conn.close()
    if not sb_url or not sb_key:
        return {'configured': False, 'supabase_url': '', 'auth_reachable': False, 'db_tables_ready': False, 'service_role_configured': False, 'local_counts': local_counts, 'remote_counts': {}, 'hint': 'Paste your SUPABASE_URL and SUPABASE_ANON_KEY from Supabase Dashboard -> Project Settings -> API.'}
    auth_ok = False
    db_ready = False
    remote_counts = {}
    try:
        ra = core._sb_get(f'{sb_url}/auth/v1/settings', headers={'apikey': sb_key}, timeout=8)
        auth_ok = ra.status_code == 200
    except Exception:
        pass
    try:
        rd = core._sb_get(f'{sb_url}/rest/v1/users?select=id&limit=1', headers=core.sb_db_headers(prefer=''), timeout=8)
        if rd.status_code in (200, 206):
            db_ready = True
            for tbl in ('users', 'workspaces', 'leads', 'email_logs'):
                rows = core.sb_rest('GET', tbl, params={'select': 'id', 'limit': '1000'}, prefer='')
                if isinstance(rows, list):
                    remote_counts[tbl] = len(rows)
    except Exception:
        pass
    return {'configured': True, 'supabase_url': sb_url, 'auth_reachable': auth_ok, 'db_tables_ready': db_ready, 'service_role_configured': bool(srv_key), 'local_counts': local_counts, 'remote_counts': remote_counts, 'hint': 'Connected!' if auth_ok and db_ready else 'Auth is connected! Copy the SQL Schema below and run it in your Supabase SQL Editor to create the database tables.' if auth_ok else 'Check your SUPABASE_URL and SUPABASE_ANON_KEY.'}

@core.app.post('/api/supabase/sync')
def trigger_supabase_sync(authorization: str=core.Header(None)):
    core.require_admin(authorization)
    result = core.sync_all_to_supabase()
    if not result['ok']:
        raise core.HTTPException(502, result.get('error', 'Supabase sync failed'))
    return result

@core.app.get('/api/supabase/schema')
def get_supabase_schema():
    schema_path = core.Path(__file__).resolve().parent.parent/'supabase/migrations/202610270001_app_database.sql'
    sql = schema_path.read_text(encoding='utf-8')
    return {'sql': sql}

@core.app.get('/api/supabase/emails')
def list_supabase_emails(authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    rows = [dict(r) for r in conn.execute('SELECT * FROM email_logs WHERE user_id=? ORDER BY id DESC LIMIT 25', (user['id'],)).fetchall()]
    conn.close()
    return rows

@core.app.post('/api/auth/supabase-sync')
def supabase_sync(b: core.SupabaseSync):
    if core.database.is_postgres():
        user = core.verify_supabase_access_token(b.access_token)
        if not user:
            raise core.HTTPException(401, 'Invalid or expired Supabase session')
        return {'user': user, 'token': b.access_token, 'auth_provider': 'supabase'}
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key:
        raise core.HTTPException(400, 'Supabase is not configured yet. Add SUPABASE_URL and SUPABASE_ANON_KEY.')
    try:
        r = core._sb_get(f'{sb_url}/auth/v1/user', headers={'apikey': sb_key, 'Authorization': f'Bearer {b.access_token}'}, timeout=15)
    except core.httpx.RequestError as e:
        raise core.HTTPException(503, f'Supabase connection error: {e}')
    if r.status_code != 200:
        raise core.HTTPException(401, 'Invalid or expired Supabase session token')
    data = r.json()
    email = (data.get('email') or '').strip().lower()
    if not email:
        raise core.HTTPException(400, 'Supabase account did not provide an email address')
    meta = data.get('user_metadata') or {}
    full_name = (b.name or '').strip() or meta.get('full_name') or meta.get('name') or email.split('@')[0].title()
    sb_uid = data.get('id') or ''
    res = core.sync_local_user_from_supabase(email=email, full_name=full_name, supabase_uid=sb_uid)
    core.commerce.verified_email(res['user']['id'], bool(data.get('email_confirmed_at')))
    return res | {'supabase_access_token': b.access_token, 'auth_provider': 'supabase'}

@core.app.post('/api/auth/register')
def register(b: core.Register):
    email = b.email.strip().lower()
    full_name = (b.name or '').strip() or email.split('@')[0].title()
    if not email or '@' not in email:
        raise core.HTTPException(400, 'Valid email required')
    if len(b.password) < 6:
        raise core.HTTPException(400, 'Password must be at least 6 characters')
    sb_url, sb_key = core.supabase_config()
    if sb_url and sb_key:
        try:
            r = core._sb_post(f'{sb_url}/auth/v1/signup', headers={'apikey': sb_key, 'Content-Type': 'application/json'}, json={'email': email, 'password': b.password, 'data': {'full_name': full_name}}, timeout=15)
        except core.httpx.RequestError as e:
            raise core.HTTPException(503, f'Supabase connection error: {e}')
        data = r.json() if r.content else {}
        if r.status_code not in (200, 201):
            msg = data.get('msg') or data.get('error_description') or data.get('message') or 'Supabase sign up failed'
            raise core.HTTPException(400, msg)
        if not data.get('access_token'):
            return {'confirmation_required': True, 'auth_provider': 'supabase', 'msg': 'Check your email to confirm your account, then log in.'}
        user_obj = data.get('user') if isinstance(data.get('user'), dict) else data
        sb_uid = user_obj.get('id') or ''
        synced = core.sync_local_user_from_supabase(email=email, full_name=full_name, supabase_uid=sb_uid, password=b.password)
        core.commerce.verified_email(synced['user']['id'], bool(user_obj.get('email_confirmed_at')))
        core.record_email_log(email, '🎉 Welcome to Comment → Money!', f'Hi {full_name}, your account ({email}) is now registered with Supabase Auth & Database.', email_type='welcome', provider='supabase_auth', status='sent', user_id=synced['user']['id'])
        return synced | {'token': data.get('access_token') if core.database.is_postgres() else synced['token'], 'supabase_access_token': data.get('access_token'), 'confirmation_required': bool(not data.get('access_token') and user_obj.get('identities') is not None), 'auth_provider': 'supabase'}
    if core.database.is_postgres() or core.os.getenv('APP_ENV') == 'production':
        raise core.HTTPException(503, 'Verified email authentication must be configured before signup')
    if email in core.ADMIN_EMAILS:
        raise core.HTTPException(403, 'Administrator accounts require verified Supabase authentication or server provisioning')
    conn = core.get_db()
    existing = conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
    if existing:
        conn.close()
        raise core.HTTPException(400, 'An account with this email already exists')
    now = core.datetime.now(core.timezone.utc).isoformat()
    pwd_hash = core.hash_password(b.password)
    cur = conn.execute('INSERT INTO users(email, password_hash, created_at, name) VALUES(?,?,?,?)', (email, pwd_hash, now, full_name))
    uid = cur.lastrowid
    conn.execute("INSERT INTO workspaces(user_id, name, pitch, signals, rules) VALUES(?, 'My First Product', '', '', 'No links. No emojis spam.')", (uid,))
    conn.commit()
    conn.close()
    token = core.create_access_token(uid, email)
    return {'token': token, 'user': {'id': uid, 'email': email, 'name': full_name}, 'auth_provider': 'local'}

@core.app.post('/api/auth/login')
def login(b: core.Login):
    email = b.email.strip().lower()
    sb_url, sb_key = core.supabase_config()
    if sb_url and sb_key:
        try:
            r = core._sb_post(f'{sb_url}/auth/v1/token?grant_type=password', headers={'apikey': sb_key, 'Content-Type': 'application/json'}, json={'email': email, 'password': b.password}, timeout=15)
        except core.httpx.RequestError as e:
            raise core.HTTPException(503, f'Supabase connection error: {e}')
        data = r.json() if r.content else {}
        if r.status_code != 200:
            msg = data.get('error_description') or data.get('msg') or data.get('message') or 'Invalid email or password'
            raise core.HTTPException(401, msg)
        user_obj = data.get('user') or {}
        meta = user_obj.get('user_metadata') or {}
        full_name = meta.get('full_name') or meta.get('name') or email.split('@')[0].title()
        sb_uid = user_obj.get('id') or ''
        synced = core.sync_local_user_from_supabase(email=email, full_name=full_name, supabase_uid=sb_uid, password=b.password)
        core.commerce.verified_email(synced['user']['id'], bool(user_obj.get('email_confirmed_at')))
        return synced | {'token': data.get('access_token') if core.database.is_postgres() else synced['token'], 'supabase_access_token': data.get('access_token'), 'auth_provider': 'supabase'}
    if core.database.is_postgres():
        raise core.HTTPException(503, 'Supabase Auth must be configured')
    conn = core.get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    if not user or not core.verify_password(user['password_hash'], b.password):
        raise core.HTTPException(401, 'Invalid email or password')
    token = core.create_access_token(user['id'], user['email'])
    uname = user['name'] if 'name' in user.keys() and user['name'] else email.split('@')[0].title()
    return {'token': token, 'user': {'id': user['id'], 'email': user['email'], 'name': uname}, 'auth_provider': 'local'}

@core.app.post('/api/free-preview')
def free_preview(b: core.FreePreview, request: core.Request=None):
    q = (b.query or '').strip()
    if not q:
        raise core.HTTPException(400, 'Please enter a YouTube link, channel, or keyword')
    vids = core.video_ids(q)
    if not vids:
        items = core.yt('search', part='snippet', q=q, type='video', maxResults=3).get('items', [])
        vids = [item.get('id', {}).get('videoId') for item in items if item.get('id', {}).get('videoId')]
    if not vids:
        return {'video': None, 'leads': [], 'message': 'No videos found. Try a specific video or a different search.', 'qualified': False}
    vid = vids[0]
    cs = sorted((c for c in core.comments(vid, 35) if core.sieve(c)), key=lambda c: core.source_date(c.get('published_at')), reverse=True)
    picked = []
    for c in cs[:5]:
        picked.append({'author': c['author'], 'published_at': c.get('published_at') or '', 'time': c.get('published_at') or 'Date unavailable', 'text': c['text'], 'intent': 'Unqualified comment', 'reply': '', 'comment_id': c['id'], 'link': f"https://www.youtube.com/watch?v={vid}&lc={c['id']}", 'video_url': f'https://www.youtube.com/watch?v={vid}'})
    if request is not None:request.state.preview_result_count=len(picked)
    first = cs[0] if cs else {}
    return {'qualified': False, 'message': 'Real public comments, not verified leads. Join the waitlist for product matching.', 'video': {'video_id': vid, 'title': first.get('title') or 'YouTube video', 'channel': first.get('channel') or '', 'video_url': f'https://www.youtube.com/watch?v={vid}', 'channel_url': f"https://www.youtube.com/channel/{first['cid']}" if first.get('cid') else f'https://www.youtube.com/watch?v={vid}', 'thumbnail': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg', 'meta': 'Source: YouTube Data API'}, 'leads': picked}
