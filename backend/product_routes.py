"""Product Routes: focused API/service functions."""
from backend import runtime as core

@core.app.get('/api/auth/me')
def me(authorization: str=core.Header(None)):
    return core.get_current_user(authorization)

@core.app.get('/api/workspaces')
def list_ws(authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    rows = [dict(r) for r in conn.execute('SELECT * FROM workspaces WHERE user_id=? ORDER BY id ASC', (user['id'],))]
    conn.close()
    for row in rows:
        row['profile'] = core.workspace_profile(row)
    return rows

@core.app.post('/api/workspaces')
def add_ws(w: core.WS, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    name = w.name.strip()
    if not name:
        raise core.HTTPException(400, 'Workspace name cannot be empty')
    conn = core.get_db()
    existing = conn.execute('SELECT id, pitch FROM workspaces WHERE user_id=? AND LOWER(name)=LOWER(?)', (user['id'], name)).fetchone()
    core.commerce.product_limit(conn, user['id'], existing['id'] if existing else None)
    if existing:
        old_words = set(core.re.findall('[a-zA-Z]{4,}', (existing['pitch'] or '').lower()))
        new_words = set(core.re.findall('[a-zA-Z]{4,}', (w.pitch or '').lower()))
        if old_words and new_words and (len(old_words & new_words) / max(1, min(len(old_words), len(new_words))) < 0.25):
            core.logger.info('Workspace %s matching criteria changed; previous analyses require reassessment', existing['id'])
        conn.execute('UPDATE workspaces SET name=?, pitch=?, signals=?, rules=?, blocklist=? WHERE id=?', (name, w.pitch, w.signals, w.rules, w.blocklist, existing['id']))
        conn.commit()
        wid = existing['id']
    else:
        c = conn.execute('INSERT INTO workspaces(user_id, name,pitch,signals,rules,blocklist) VALUES(?,?,?,?,?,?)', (user['id'], name, w.pitch, w.signals, w.rules, w.blocklist))
        conn.commit()
        wid = c.lastrowid
    if w.profile is not None:
        conn.execute('UPDATE workspaces SET profile=? WHERE id=?', (core.json.dumps(w.profile.model_dump(), ensure_ascii=False), wid))
        conn.commit()
    ws_row = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
    conn.close()
    if ws_row:
        core.sb_sync_workspace_row(dict(ws_row))
    return {'id': wid}

@core.app.post('/api/workspaces/{wid}/blocklist')
def update_blocklist(wid: int, b: core.BlocklistUpdate, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    core.check_ws_owner(conn, wid, user['id'])
    conn.execute('UPDATE workspaces SET blocklist=? WHERE id=?', (b.blocklist, wid))
    conn.commit()
    ws_row = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
    conn.close()
    if ws_row:
        core.sb_sync_workspace_row(dict(ws_row))
    return {'ok': True, 'blocklist': b.blocklist}

@core.app.post('/api/auto')
def auto(b: core.Auto, request: core.Request=None, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    core.commerce.require_processing(user['id'], request)
    conn = core.get_db()
    ws = core.check_ws_owner(conn, b.workspace_id, user['id'])
    conn.close()
    plan = core.plan_of(user['id'])
    per_video = max(10, min(b.per_video, 80))
    max_videos = max(1, min(b.max_videos, plan['max_videos']))
    jid, run_id = core.reserve_search(user['id'], ws['id'], 'auto', 50, 'Starting automatic search...')
    core.commerce.submit_job(core.run_auto_job, jid, ws['id'], per_video, max_videos, False, user['email'], run_id, plan['queries'])
    return {'job_id': jid, 'job': jid}

@core.app.post('/api/scan')
def scan(b: core.Scan, request: core.Request=None, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    core.commerce.require_processing(user['id'], request)
    conn = core.get_db()
    ws = core.check_ws_owner(conn, b.workspace_id, user['id'])
    conn.close()
    plan = core.plan_of(user['id'])
    urls = [u for u in b.urls if u and u.strip()][:5 if plan['key'] == 'free' else 30]
    if not urls:
        raise core.HTTPException(400, 'Please add at least one video or channel link')
    per_video = max(10, min(b.per_video, 80))
    jid, run_id = core.reserve_search(user['id'], ws['id'], 'scan', max(10, len(urls) * 12), 'Starting scan...')
    core.commerce.submit_job(core.run_scan_job, jid, ws['id'], urls, per_video, user['email'], run_id)
    return {'job_id': jid, 'job': jid}

@core.app.post('/api/workspaces/{wid}/reassess')
def reassess(wid: int, request: core.Request=None, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    core.commerce.require_processing(user['id'], request)
    conn = core.get_db()
    core.check_ws_owner(conn, wid, user['id'])
    conn.close()
    jid, run_id = core.reserve_search(user['id'], wid, 'reassess', 0, 'Reassessing saved comments...')
    core.commerce.submit_job(core.run_reassessment, jid, wid, run_id)
    return {'job_id': jid}

@core.app.get('/api/job/{jid}')
def get_job(jid: int, authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    j = conn.execute('SELECT * FROM jobs WHERE id=? AND user_id=?', (jid, user['id'])).fetchone()
    conn.close()
    if not j:
        raise core.HTTPException(404, 'Job not found')
    res = core.json.loads(j['result']) if j['result'] else None
    return {'id': j['id'], 'workspace_id': j['workspace_id'], 'type': j['type'], 'status': j['status'], 'msg': j['msg'], 'progress': j['progress'], 'done': j['status'] in ('done', 'error', 'interrupted'), 'error': j['error'], 'result': res}

def _public_host(host: str) -> bool:
    try:
        for info in core.socket.getaddrinfo(host, None):
            ip = core.ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False

def fetch_site_text(url: str, limit: int=6000) -> str:
    """Read a public website (or GitHub README) as plain text. Refuses private/internal addresses."""
    url = (url or '').strip()
    if not core.re.match('^https?://', url, core.re.I):
        url = 'https://' + url
    m = core.re.match('^https?://github\\.com/([^/]+)/([^/#?]+)/?$', url, core.re.I)
    if m:
        url = f'https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD/README.md'
    for _ in range(4):
        host = core.urlparse(url).hostname or ''
        if not host or not core._public_host(host):
            raise core.HTTPException(400, "That link can't be read. Please paste a public website address.")
        try:
            r = core.httpx.get(url, timeout=10, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0 CommentMoneyBot'})
        except core.httpx.RequestError:
            raise core.HTTPException(400, 'Could not open that website. Check the link, or describe your product in one line instead.')
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('location'):
            url = str(core.httpx.URL(url).join(r.headers['location']))
            continue
        if r.status_code != 200:
            raise core.HTTPException(400, f'That website returned an error ({r.status_code}). Describe your product in one line instead.')
        text = r.text[:400000]
        text = core.re.sub('(?is)<(script|style|noscript|svg)[^>]*>.*?</\\1>', ' ', text)
        text = core.re.sub('(?s)<[^>]+>', ' ', text)
        text = core.re.sub('\\s+', ' ', text).strip()
        return text[:limit]
    raise core.HTTPException(400, 'Too many redirects on that link.')

@core.app.post('/api/onboard/suggest')
def onboard_suggest(b: core.Onboard, authorization: str=core.Header(None)):
    core.get_current_user(authorization)
    name = b.name.strip()
    about = b.about.strip()
    features_in = b.features.strip()
    if not name:
        raise core.HTTPException(400, 'Please enter your business or app name')
    site, own = ('', about)
    link = core.re.search('(https?://\\S+|\\b(?:www\\.)?[\\w-]+\\.(?:com|in|co|io|app|ai|org|net|store|shop|dev|me)\\b\\S*)', about, core.re.I)
    if link:
        site = core.fetch_site_text(link.group(1))
        own = about.replace(link.group(1), '').strip()
    if not site and len(own) + len(features_in) < 8:
        raise core.HTTPException(400, 'Please tell us in one line what you sell, or paste your website link')
    d = core.gem(core.ONBOARD_PROMPT.format(name=name, biz_type=b.biz_type or 'Business / App', about=own or '(none, see website)', features=features_in or '(extract from description or website)', audience=core.json.dumps(b.profile.model_dump(), ensure_ascii=False) if b.profile else b.audience or '(not given)', site=site or '(none)'))
    if not isinstance(d, dict):
        raise core.HTTPException(502, 'The AI gave an unexpected answer. Please try again.')
    raw_tiers = d.get('tiers') if isinstance(d.get('tiers'), dict) else {}
    high_kws = [str(k).strip() for k in raw_tiers.get('high', []) if str(k).strip()][:6]
    med_kws = [str(k).strip() for k in raw_tiers.get('medium', []) if str(k).strip()][:6]
    low_kws = [str(k).strip() for k in raw_tiers.get('low', []) if str(k).strip()][:6]
    kws = [str(k).strip() for k in d.get('keywords', []) if str(k).strip()][:14]
    if not kws and (high_kws or med_kws or low_kws):
        kws = (high_kws + med_kws + low_kws)[:14]
    if not (high_kws or med_kws or low_kws) and kws:
        high_kws = kws[:4]
        med_kws = kws[4:8]
        low_kws = kws[8:12]
    feats = [str(f).strip() for f in d.get('features', []) if str(f).strip()][:8]
    if not feats and features_in:
        feats = [x.strip() for x in core.re.split('[,;\\n]+', features_in) if x.strip()][:8]
    comp = [x.strip() for x in core.re.split('[,;\\n]+', b.profile.competitors) if x.strip()][:5] if b.profile else []
    pitch = str(d.get('pitch', '')).strip()
    if feats and 'feature' not in pitch.lower() and (len(feats) >= 2):
        pitch += ' Main features: ' + ', '.join(feats) + '.'
    if comp and 'alternative' not in pitch.lower() and ('competitor' not in pitch.lower()):
        pitch += ' Alternatives people may compare it to: ' + ', '.join(comp) + '.'
    return {'pitch': pitch, 'profile': b.profile.model_dump() if b.profile else {}, 'features': feats, 'tiers': {'high': high_kws, 'medium': med_kws, 'low': low_kws}, 'keywords': kws, 'competitors': comp, 'question': d.get('question', ''), 'read_website': bool(site)}

@core.app.post('/api/describe')
def describe(b: core.Describe, authorization: str=core.Header(None)):
    core.get_current_user(authorization)
    return core.gem(core.DESC_PROMPT.format(name=b.name, rough=b.rough))

@core.app.get('/api/leads')
def leads(workspace_id: int, min_score: int=60, status: str='new', authorization: str=core.Header(None)):
    user = core.get_current_user(authorization)
    conn = core.get_db()
    ws = core.check_ws_owner(conn, workspace_id, user['id'])
    blocklist_str = ws['blocklist'] if ws and 'blocklist' in ws.keys() and ws['blocklist'] else ''
    revision = core.workspace_revision(ws)
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
    out, locked = ([], [])
    for r in rows:
        d = dict(r)
        if not core.commerce.source_visible(d):
            continue
        d['analysis_stale'] = d.get('analysis_revision') != revision or d.get('analysis_state') != 'complete'
        d['evidence'] = core.json_object(d.get('evidence'))
        if core.is_blocked(d.get('author', ''), d.get('text', ''), blocklist_str):
            continue
        if capped and (not d.get('unlocked')):
            locked.append({'id': d['id'], 'locked': True, 'score': d['score'], 'status': d['status'], 'feedback': ''})
            continue
        cid = d.get('channel_id') or ''
        out.append(d | {'locked': False, 'link': f"https://www.youtube.com/watch?v={r['video_id']}&lc={r['comment_id']}", 'video_url': f"https://www.youtube.com/watch?v={r['video_id']}", 'channel': d.get('channel_title') or '', 'channel_url': f'https://www.youtube.com/channel/{cid}' if cid else '', 'feedback': r['feedback'] if 'feedback' in r.keys() and r['feedback'] else ''})
    return out + locked
