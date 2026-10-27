"""Jobs: focused API/service functions."""
from backend import runtime as core

def update_job(jid: int, msg: str=None, status: str=None, progress: int=None, result: dict=None, error: str=None):
    conn = core.get_db()
    now = core.datetime.now(core.timezone.utc).isoformat()
    updates, vals = (['updated_at=?'], [now])
    if msg is not None:
        updates.append('msg=?')
        vals.append(msg)
    if status is not None:
        updates.append('status=?')
        vals.append(status)
    if progress is not None:
        updates.append('progress=?')
        vals.append(progress)
    if result is not None:
        updates.append('result=?')
        vals.append(core.json.dumps(result))
    if error is not None:
        updates.append('error=?')
        vals.append(error)
    vals.append(jid)
    conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    if status in ('done', 'error'):
        core.sb_sync_job_row(jid)

@core.track_run
def run_auto_job(jid: int, wid: int, per_video: int, max_videos: int, is_scheduled: bool=False, recipient_email: str=None, run_id: int=None, n_queries: int=8):
    searched = False
    try:
        conn = core.get_db()
        ws = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
        conn.close()
        if not ws:
            core.update_job(jid, status='error', error='Workspace not found', msg='Workspace not found')
            core.finish_run(run_id, 'failed', units=0)
            return
        core.update_job(jid, msg='Writing YouTube search queries with AI...', progress=10)
        qs_res = core.gem(core.QUERY_PROMPT.format(name=ws['name'], pitch=core.matching_pitch(ws), signals=ws['signals'] or ''))
        qs = (qs_res.get('queries', []) if isinstance(qs_res, dict) else [])[:n_queries]
        if not qs:
            qs = [f"{ws['name']} review", f"alternative to {ws['name']}", f"{ws['pitch'][:40]}"][:n_queries]
        core.update_job(jid, msg=f'Searching YouTube with {len(qs)} queries...', progress=20)
        searched = True
        items_by_id = {}
        for q in qs:
            items = core.yt('search', part='snippet', q=q, type='video', maxResults=10).get('items', [])
            for rank, item in enumerate(items):
                vid = item.get('id', {}).get('videoId')
                if vid and vid not in items_by_id:
                    sn = item.get('snippet') or {}
                    items_by_id[vid] = {'id': vid, 'rank': rank, 'title': sn.get('title') or '', 'desc': sn.get('description') or ''}
        ids = list(items_by_id.keys())
        core.update_job(jid, msg=f'Found {len(ids)} unique videos. Ranking by relevance & comments...', progress=35)
        stats = []
        for k in range(0, len(ids), 50):
            stats += core.yt('videos', part='statistics', id=','.join(ids[k:k + 50])).get('items', [])
        stop = {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'how', 'what', 'why', 'when', 'where', 'who', 'are', 'was', 'were', 'have', 'has', 'had', 'not', 'but', 'can', 'all', 'one', 'out', 'day', 'get', 'use', 'new', 'best', 'top', 'full', 'vlog', 'vlogs', 'video', 'videos', 'shorts', 'official', 'episode', 'part', 'india', 'indian', 'abroad', 'living', 'review', 'reviews', 'price', 'cost', 'free', 'app', 'apps', 'tool', 'tools', 'online', 'using', 'make', 'into', 'more', 'most', 'very', 'really', 'good', 'bad', 'better', 'worst', 'life', 'people', 'time', 'year', 'years', 'because', 'their', 'designed', 'directly', 'inside', 'normal', 'works', 'sends', 'competitors', '2024', '2025', '2026', '2027', (ws['name'] or '').strip().lower()}
        kws = {w for w in core.re.findall('[a-zA-Z]{3,}', f"{ws['pitch']} {ws['signals'] or ''} {' '.join(qs)}".lower()) if w not in stop}
        scored = []
        for x in stats:
            vid = x['id']
            cc_val = int(x.get('statistics', {}).get('commentCount', 0))
            if cc_val < 5:
                continue
            info = items_by_id.get(vid, {})
            t_words = set(core.re.findall('[a-zA-Z]{3,}', info.get('title', '').lower()))
            d_words = set(core.re.findall('[a-zA-Z]{3,}', info.get('desc', '').lower()))
            t_match = len(t_words & kws)
            d_match = len((t_words | d_words) & kws)
            if kws and (info.get('title') or info.get('desc')) and (d_match == 0):
                continue
            scored.append((t_match >= 2, t_match, d_match, min(cc_val, 300), -info.get('rank', 99), vid))
        scored.sort(reverse=True)
        vids = [row[5] for row in scored][:max_videos]
        if not vids:
            cc = lambda x: int(x.get('statistics', {}).get('commentCount', 0))
            vids = [x['id'] for x in sorted(stats, key=cc, reverse=True) if cc(x) >= 5][:max_videos] or ids[:max_videos]
        core.update_job(jid, msg=f'Reading comments from top {len(vids)} videos...', progress=40)
        scan_res = core.run_scan(ws, vids, per_video, jid=jid)
        conn = core.get_db()
        user_id = ws['user_id'] if 'user_id' in ws.keys() and ws['user_id'] else 1
        details = f'Auto run on {len(vids)} videos'
        if run_id:
            conn.execute("UPDATE runs SET new_leads_count=?, status='completed', details=? WHERE id=?", (scan_res['hot_leads'], details, run_id))
        else:
            conn.execute('INSERT INTO runs(workspace_id, user_id, units_used, new_leads_count, status, details, created_at) VALUES (?,?,?,?,?,?,?)', (ws['id'], user_id, core.ESTIMATED_RUN_QUOTA, scan_res['hot_leads'], 'completed', details, core.datetime.now(core.timezone.utc).isoformat()))
        conn.commit()
        core.unlock_top_leads(conn, user_id, ws['id'])
        visible, hidden = core.alertable(conn, user_id, ws['id'], scan_res.get('new_leads', []))
        conn.close()
        if visible:
            core.send_lead_alert(ws['name'], visible, recipient_email=recipient_email, locked_count=hidden)
        final_msg = f"Checked {scan_res['videos']} videos, read {scan_res.get('comments_read', 0)} comments ({scan_res['scanned']} new real comments), found {scan_res['hot_leads']} leads."
        core.update_job(jid, status='done', msg=final_msg, progress=100, result={'videos': scan_res['videos'], 'comments_read': scan_res.get('comments_read', 0), 'scanned': scan_res['scanned'], 'hot_leads': scan_res['hot_leads'], 'queries': qs})
    except core.HTTPException as e:
        core.update_job(jid, status='error', error=str(e.detail), msg=str(e.detail))
        core.finish_run(run_id, 'failed', units=None if searched else 0)
    except Exception as e:
        core.update_job(jid, status='error', error=str(e), msg=f'Job failed: {e}')
        core.finish_run(run_id, 'failed', units=None if searched else 0)

@core.track_run
def run_scan_job(jid: int, wid: int, urls: list[str], per_video: int, recipient_email: str=None, run_id: int=None):
    try:
        conn = core.get_db()
        ws = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
        conn.close()
        if not ws:
            core.update_job(jid, status='error', error='Workspace not found', msg='Workspace not found')
            core.finish_run(run_id, 'failed', units=0)
            return
        core.update_job(jid, msg='Parsing video/channel URLs...', progress=15)
        vids = []
        for u in urls:
            vids += core.video_ids(u.strip())
        vids = list(dict.fromkeys(vids))
        if not vids:
            core.update_job(jid, status='error', error='No valid video IDs found in provided URLs', msg='No valid video IDs found')
            core.finish_run(run_id, 'failed', units=0)
            return
        core.update_job(jid, msg=f'Found {len(vids)} videos. Reading comments...', progress=30)
        scan_res = core.run_scan(ws, vids, per_video, jid=jid)
        conn = core.get_db()
        user_id = ws['user_id'] if 'user_id' in ws.keys() and ws['user_id'] else 1
        details = f'Manual scan on {len(vids)} videos'
        if run_id:
            conn.execute("UPDATE runs SET new_leads_count=?, status='completed', details=?, units_used=? WHERE id=?", (scan_res['hot_leads'], details, len(vids) * 2, run_id))
        else:
            conn.execute('INSERT INTO runs(workspace_id, user_id, units_used, new_leads_count, status, details, created_at) VALUES (?,?,?,?,?,?,?)', (ws['id'], user_id, len(vids) * 2, scan_res['hot_leads'], 'completed', details, core.datetime.now(core.timezone.utc).isoformat()))
        conn.commit()
        core.unlock_top_leads(conn, user_id, ws['id'])
        visible, hidden = core.alertable(conn, user_id, ws['id'], scan_res.get('new_leads', []))
        conn.close()
        if visible:
            core.send_lead_alert(ws['name'], visible, recipient_email=recipient_email, locked_count=hidden)
        final_msg = f"Scanned {scan_res['scanned']} comments across {len(vids)} videos, found {scan_res['hot_leads']} hot leads."
        core.update_job(jid, status='done', msg=final_msg, progress=100, result={'videos': len(vids), 'scanned': scan_res['scanned'], 'hot_leads': scan_res['hot_leads'], 'comments_read': scan_res.get('comments_read', 0)})
    except core.HTTPException as e:
        core.update_job(jid, status='error', error=str(e.detail), msg=str(e.detail))
        core.finish_run(run_id, 'failed', units=0)
    except Exception as e:
        core.update_job(jid, status='error', error=str(e), msg=f'Scan failed: {e}')
        core.finish_run(run_id, 'failed', units=0)

def scheduled_auto_run_all():
    conn = core.get_db()
    workspaces = conn.execute('SELECT w.*, u.email as user_email FROM workspaces w LEFT JOIN users u ON w.user_id = u.id WHERE length(w.pitch) > 10').fetchall()
    conn.close()
    for ws in workspaces:
        user_id = ws['user_id'] if 'user_id' in ws.keys() and ws['user_id'] else 1
        plan = core.plan_of(user_id)
        if not plan['auto_scan']:
            continue
        recent = core.get_db()
        last = recent.execute("SELECT MAX(created_at) FROM jobs WHERE workspace_id=? AND status IN ('queued','running','done')", (ws['id'],)).fetchone()[0]
        recent.close()
        if last and core.commerce.parse(last) > core.commerce.now() - core.timedelta(days=7):
            continue
        try:
            jid, run_id = core.reserve_search(user_id, ws['id'], 'auto', 50, 'Scheduled weekly run...')
        except core.HTTPException as e:
            print(f"Skipping scheduled run for '{ws['name']}': {e.detail}")
            continue
        print(f"Executing scheduled lead search for '{ws['name']}'...")
        recipient = ws['user_email'] if 'user_email' in ws.keys() and ws['user_email'] else None
        core.commerce.submit_job(core.run_auto_job, jid, ws['id'], per_video=80, max_videos=plan['max_videos'], is_scheduled=True, recipient_email=recipient, run_id=run_id, n_queries=plan['queries'])

@core.track_run
def run_reassessment(jid, wid, run_id=None):
    conn = core.get_db()
    try:
        ws = conn.execute('SELECT * FROM workspaces WHERE id=?', (wid,)).fetchone()
        revision = core.workspace_revision(ws)
        rows = conn.execute("SELECT * FROM leads WHERE workspace_id=? AND\n            retention_expired=0 AND (analysis_revision != ? OR analysis_state != 'complete') ORDER BY published_at DESC LIMIT 500", (wid, revision)).fetchall()
        pool = [{'id': r['comment_id'], 'vid': r['video_id'], 'title': r['video_title'], 'author': r['author'], 'text': r['text'], 'channel': r['channel_title'], 'cid': r['channel_id'], 'published_at': r['published_at'], 'source_updated_at': r['source_updated_at'], 'retrieved_at': r['retrieved_at']} for r in rows if core.commerce.source_visible(r) and (not core.is_blocked(r['author'], r['text'], ws['blocklist'] or ''))]
        token = core._API_CONTEXT.set(core._API_CONTEXT.get() | {'workspace_id': wid, 'user_id': ws['user_id']})
        try:
            core.score_pool(ws, pool, conn, jid)
        finally:
            core._API_CONTEXT.reset(token)
        core.unlock_top_leads(conn, ws['user_id'], wid)
        conn.commit()
        saved = conn.execute('SELECT * FROM leads WHERE workspace_id=?', (wid,)).fetchall()
        core.sb_sync_leads_rows(saved)
        core.finish_run(run_id, 'completed', new_leads=0, units=0)
        core.update_job(jid, status='done', progress=100, msg=f'Reassessed {len(pool)} saved comments; no new YouTube requests', result={'scanned': len(pool)})
    except Exception as exc:
        core.finish_run(run_id, 'failed', units=0)
        core.logger.exception('Reassessment failed for job %s', jid)
        core.update_job(jid, status='error', error='Reassessment failed. Your saved comments and outreach history are preserved; try again.')
    finally:
        conn.close()
