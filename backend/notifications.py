"""Notifications: focused API/service functions."""
from backend import runtime as core

def record_email_log(to_email: str, subject: str, body: str, email_type: str='lead_alert', provider: str='supabase', status: str='sent', user_id: int=None):
    if email_type == 'lead_alert':
        body = core.commerce.ALERT_LOG_BODY
    now = core.datetime.now(core.timezone.utc).isoformat()
    conn = core.get_db()
    if user_id is None:
        owner = conn.execute('SELECT id FROM users WHERE email=?', ((to_email or '').strip().lower(),)).fetchone()
        user_id = owner['id'] if owner else None
    cur = conn.execute('INSERT INTO email_logs(user_id, to_email, subject, body, email_type, provider, status, created_at) VALUES (?,?,?,?,?,?,?,?)', (user_id, to_email or '', subject or '', body or '', email_type, provider, status, now))
    eid = cur.lastrowid
    conn.commit()
    row = conn.execute('SELECT * FROM email_logs WHERE id=?', (eid,)).fetchone()
    conn.close()
    if row:
        core._run_sb_async(core.sb_rest, 'POST', 'email_logs', params={'on_conflict': 'id'}, json_body=dict(row), prefer='resolution=merge-duplicates,return=minimal')
    return eid

def send_telegram_alert(text: str) -> bool:
    token = core.os.getenv('TELEGRAM_BOT_TOKEN') or core.TELEGRAM_BOT_TOKEN
    chat_id = core.os.getenv('TELEGRAM_CHAT_ID') or core.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False
    try:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        r = core.httpx.post(url, json={'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True}, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f'Telegram alert error: {e}')
        return False

def send_email_alert(to_email: str, subject: str, body: str, email_type: str='lead_alert', user_id: int=1) -> bool:
    host = core.os.getenv('SMTP_HOST') or core.SMTP_HOST
    user = core.os.getenv('SMTP_USER') or core.SMTP_USER
    pwd = core.os.getenv('SMTP_PASSWORD') or core.SMTP_PASSWORD
    recipient = (to_email or core.os.getenv('ALERT_EMAIL_TO') or core.ALERT_EMAIL_TO or '').strip()
    if not recipient:
        return False
    if host and user and pwd:
        try:
            msg = core.MIMEMultipart()
            msg['From'] = user
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(core.MIMEText(body, 'plain'))
            with core.smtplib.SMTP(host, core.SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(user, pwd)
                server.sendmail(user, [recipient], msg.as_string())
            core.record_email_log(recipient, subject, body, email_type=email_type, provider='smtp', status='sent', user_id=user_id)
            return True
        except Exception as e:
            print(f'Email alert SMTP error: {e}')
    resend_key = (core.os.getenv('RESEND_API_KEY') or '').strip()
    if resend_key:
        try:
            from_addr = core.os.getenv('RESEND_FROM_EMAIL', 'Comment to Money <onboarding@resend.dev>')
            r = core.httpx.post('https://api.resend.com/emails', headers={'Authorization': f'Bearer {resend_key}', 'Content-Type': 'application/json'}, json={'from': from_addr, 'to': [recipient], 'subject': subject, 'text': body}, timeout=15)
            if r.status_code in (200, 201):
                core.record_email_log(recipient, subject, body, email_type=email_type, provider='supabase_resend', status='sent', user_id=user_id)
                return True
        except Exception as e:
            print(f'Resend email error: {e}')
    sb_url, sb_key = core.supabase_config()
    if sb_url and sb_key:
        active_key = core.supabase_service_key() or sb_key
        edge_sent = False
        try:
            r = core.httpx.post(f'{sb_url}/functions/v1/send-email', headers={'apikey': active_key, 'Authorization': f'Bearer {active_key}', 'Content-Type': 'application/json'}, json={'to': recipient, 'subject': subject, 'text': body}, timeout=10)
            if r.status_code == 200:
                edge_sent = True
        except Exception:
            pass
        core.record_email_log(recipient, subject, body, email_type=email_type, provider='supabase_edge' if edge_sent else 'supabase_outbox', status='sent' if edge_sent else 'queued_in_supabase', user_id=user_id)
        return True
    return False

def send_lead_alert(workspace_name: str, new_leads: list[dict], recipient_email: str=None, locked_count: int=0):
    if core.database.is_postgres() and core.os.getenv('ENABLE_LEAD_ALERTS') != 'true':
        return {'email': False, 'telegram': False}
    if not new_leads:
        return
    count = len(new_leads)
    subject = f"🎯 {count} new {workspace_name} lead{('s' if count > 1 else '')} found on YouTube!"
    lines = [f'{subject}\n']
    for idx, l in enumerate(new_leads[:5], 1):
        vid = l.get('video_id') or l.get('vid') or ''
        cid = l.get('comment_id') or l.get('id') or ''
        vtitle = (l.get('video_title') or l.get('title') or '')[:50]
        link = l.get('link') or f'https://www.youtube.com/watch?v={vid}&lc={cid}'
        lines.append(f"{idx}. {l.get('author')} (Score: {l.get('score')}) on '{vtitle}'")
        lines.append(f'''Comment: "{l.get('text')}"''')
        lines.append(f"Why: {l.get('reason')}")
        lines.append(f'''Draft reply: "{l.get('reply')}"''')
        lines.append(f'Link: {link}\n')
    if count > 5:
        lines.append(f'...and {count - 5} more leads available in your dashboard.')
    if locked_count:
        lines.append(f"{locked_count} more lead{('s' if locked_count > 1 else '')} found but locked on the free plan.")
    full_text = '\n'.join(lines)
    mail_sent = core.send_email_alert(recipient_email, subject, full_text)
    tg_sent = core.send_telegram_alert(full_text)
    return {'email': mail_sent, 'telegram': tg_sent}
