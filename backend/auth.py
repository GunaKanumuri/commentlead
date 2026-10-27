"""Auth: focused API/service functions."""
from backend import runtime as core

def provision_supabase_user(email, full_name, supabase_uid):
    """Map a server-verified Supabase identity to its private application profile."""
    if not supabase_uid:
        raise core.HTTPException(401, 'Supabase identity required')
    email = email.strip().lower()
    name = (full_name or '').strip() or email.split('@')[0]
    conn = core.get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM users WHERE supabase_uid=? OR lower(email)=? ORDER BY id LIMIT 1', (supabase_uid, email)).fetchone()
        if row:
            if row['deleted_at'] or conn.execute("SELECT 1 FROM deletion_requests WHERE user_id=? AND status!='done'", (row['id'],)).fetchone():
                raise core.HTTPException(401, 'Account deletion is in progress')
            if row['supabase_uid'] and row['supabase_uid'] != supabase_uid:
                raise core.HTTPException(409, 'This email is already linked to another identity')
            uid = row['id']
            conn.execute("UPDATE users SET email=?,name=?,supabase_uid=?,email_verified=1,password_hash='' WHERE id=?", (email, name, supabase_uid, uid))
        else:
            uid = conn.execute("INSERT INTO users(email,name,supabase_uid,password_hash,email_verified,created_at) VALUES(?,?,?,'',1,?)", (email, name, supabase_uid, core.commerce.iso(core.commerce.now()))).lastrowid
            conn.execute("INSERT INTO workspaces(user_id,name,pitch,signals,rules) VALUES(?,'My First Product','','','No spam.')", (uid,))
        profile = conn.execute('SELECT id,email,name,supabase_uid,created_at FROM users WHERE id=?', (uid,)).fetchone()
        conn.commit()
        return {'user': dict(profile)}
    finally:
        conn.close()

def hash_password(password: str) -> str:
    salt = core.secrets.token_hex(16)
    key = core.hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f'{salt}:{key.hex()}'

def verify_password(stored: str, password: str) -> bool:
    if not stored or ':' not in stored:
        return False
    salt, key_hex = stored.split(':', 1)
    new_key = core.hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return core.secrets.compare_digest(new_key.hex(), key_hex)

def create_access_token(user_id: int, email: str) -> str:
    payload = {'sub': str(user_id), 'email': email, 'exp': core.datetime.now(core.timezone.utc) + core.timedelta(days=30), 'iat': core.datetime.now(core.timezone.utc)}
    return core.jwt.encode(payload, core.JWT_SECRET, algorithm=core.JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return core.jwt.decode(token, core.JWT_SECRET, algorithms=[core.JWT_ALGORITHM])
    except Exception:
        return None

def sync_local_user_from_supabase(email: str, full_name: str='', supabase_uid: str='', password: str='') -> dict:
    if core.database.is_postgres():
        return provision_supabase_user(email, full_name, supabase_uid)
    email = email.strip().lower()
    full_name = (full_name or '').strip() or email.split('@')[0].title()
    conn = core.get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    now = core.datetime.now(core.timezone.utc).isoformat()
    pwd_hash = core.hash_password(password) if password else ''
    if user:
        uid = user['id']
        new_name = full_name or (user['name'] if 'name' in user.keys() and user['name'] else email.split('@')[0].title())
        new_sb = supabase_uid or (user['supabase_uid'] if 'supabase_uid' in user.keys() else '')
        if password:
            conn.execute('UPDATE users SET name=?, supabase_uid=?, password_hash=? WHERE id=?', (new_name, new_sb, pwd_hash, uid))
        else:
            conn.execute('UPDATE users SET name=?, supabase_uid=? WHERE id=?', (new_name, new_sb, uid))
        conn.commit()
        full_name = new_name
    else:
        cur = conn.execute('INSERT INTO users(email, password_hash, created_at, name, supabase_uid) VALUES(?,?,?,?,?)', (email, pwd_hash, now, full_name, supabase_uid or ''))
        uid = cur.lastrowid
        conn.execute("INSERT INTO workspaces(user_id, name, pitch, signals, rules) VALUES(?, 'My First Product', '', '', 'No links. No emojis spam.')", (uid,))
        conn.commit()
    full_row = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    ws_row = conn.execute('SELECT * FROM workspaces WHERE user_id=? ORDER BY id ASC LIMIT 1', (uid,)).fetchone()
    row = conn.execute('SELECT id, email, name, supabase_uid, created_at FROM users WHERE id=?', (uid,)).fetchone()
    conn.close()
    if full_row:
        core.sb_sync_user_row(dict(full_row))
    if ws_row:
        core.sb_sync_workspace_row(dict(ws_row))
    token = core.create_access_token(uid, email)
    return {'token': token, 'user': dict(row) if row else {'id': uid, 'email': email, 'name': full_name, 'supabase_uid': supabase_uid}}

def verify_supabase_access_token(access_token: str) -> dict:
    sb_url, sb_key = core.supabase_config()
    if not sb_url or not sb_key or (not access_token):
        return None
    try:
        r = core._sb_get(f'{sb_url}/auth/v1/user', headers={'apikey': sb_key, 'Authorization': f'Bearer {access_token}'}, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if core.database.is_postgres() and (not data.get('email_confirmed_at')):
            raise core.HTTPException(401, 'Verify your email through Supabase before continuing')
        email = (data.get('email') or '').strip().lower()
        if not email:
            return None
        meta = data.get('user_metadata') or {}
        full_name = meta.get('full_name') or meta.get('name') or email.split('@')[0].title()
        sb_uid = data.get('id') or ''
        synced = core.sync_local_user_from_supabase(email=email, full_name=full_name, supabase_uid=sb_uid)
        core.commerce.verified_email(synced['user']['id'], bool(data.get('email_confirmed_at')))
        return synced['user']
    except core.HTTPException:
        raise
    except RuntimeError:
        raise core.HTTPException(503, 'The application database is unavailable') from None
    except Exception:
        return None

def get_current_user(authorization: str=core.Header(None)):
    if not isinstance(authorization, str) or not authorization.startswith('Bearer '):
        raise core.HTTPException(401, 'Authentication required. Please log in.')
    token = authorization.split(' ', 1)[1]
    payload = core.decode_token(token) if not core.database.is_postgres() else None
    if payload:
        conn = core.get_db()
        user = conn.execute("SELECT id, email, name, created_at FROM users WHERE id=? AND COALESCE(deleted_at,'')='' AND NOT EXISTS (SELECT 1 FROM deletion_requests d WHERE d.user_id=users.id AND d.status!='done')", (int(payload['sub']),)).fetchone()
        conn.close()
        if not user:
            raise core.HTTPException(401, 'Session is no longer active')
        if user:
            core._API_CONTEXT.set(core._API_CONTEXT.get() | {'user_id': user['id']})
            return dict(user)
    sb_user = core.verify_supabase_access_token(token)
    if sb_user:
        conn = core.get_db()
        try:
            inactive = conn.execute("SELECT 1 FROM users WHERE id=? AND (COALESCE(deleted_at,'')!='' OR EXISTS(SELECT 1 FROM deletion_requests d WHERE d.user_id=users.id AND d.status!='done'))", (sb_user['id'],)).fetchone()
        finally:
            conn.close()
        if inactive:
            raise core.HTTPException(401, 'Session is no longer active')
        core._API_CONTEXT.set(core._API_CONTEXT.get() | {'user_id': sb_user['id']})
        return sb_user
    raise core.HTTPException(401, 'Invalid or expired session token')

def require_admin(authorization):
    user = core.get_current_user(authorization)
    if (user['email'] or '').lower() not in core.ADMIN_EMAILS:
        raise core.HTTPException(403, 'Admins only')
    return user
