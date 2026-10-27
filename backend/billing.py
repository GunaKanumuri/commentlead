"""Billing service."""
from backend import commercial as core

def gateway(method, path, body=None):
    key = core.os.getenv('RAZORPAY_KEY_ID', '')
    secret = core.os.getenv('RAZORPAY_KEY_SECRET', '')
    if not key or not secret:
        raise core.HTTPException(503, 'Payments are not configured yet; no charge has been made')
    try:
        response = core.httpx.request(method, 'https://api.razorpay.com/v1/' + path, auth=(key, secret), json=body, timeout=15)
    except core.httpx.RequestError:
        raise core.HTTPException(503, 'Payment service unavailable; no plan has been activated')
    if response.status_code not in (200, 201):
        raise core.HTTPException(502, 'Payment provider rejected the request; contact support')
    return response.json()

def apply_subscription(subscription_id):
    current = core.gateway('GET', 'subscriptions/' + subscription_id)
    conn = core.R['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE')
        local = conn.execute('SELECT * FROM billing_subscriptions WHERE id=?', (subscription_id,)).fetchone()
        if not local:
            raise core.HTTPException(400, 'Unknown subscription')
        expected = core.os.getenv('RAZORPAY_PLAN_' + local['plan'].upper(), '')
        if current.get('id') != subscription_id or current.get('plan_id') != expected or current.get('quantity', 1) != 1:
            raise core.HTTPException(400, 'Subscription configuration mismatch')
        status = current.get('status', 'unknown')
        conn.execute('UPDATE billing_subscriptions SET status=? WHERE id=?', (status, subscription_id))
        newer = conn.execute('SELECT 1 FROM billing_subscriptions WHERE user_id=? AND created_at>? AND id!=? LIMIT 1', (local['user_id'], local['created_at'], subscription_id)).fetchone()
        if newer:
            conn.commit()
            return
        start = current.get('current_start')
        end = current.get('current_end')
        if status in ('active', 'cancelled', 'completed') and int(current.get('paid_count') or 0) > 0 and start and end and (end > core.now().timestamp()):
            conn.execute('UPDATE users SET plan=?,billing_start=?,billing_end=? WHERE id=?', (local['plan'], core.iso(core.datetime.fromtimestamp(start, core.timezone.utc)), core.iso(core.datetime.fromtimestamp(end, core.timezone.utc)), local['user_id']))
        elif status in ('halted', 'expired', 'cancelled', 'completed'):
            conn.execute('UPDATE users SET billing_end=? WHERE id=?', (core.iso(core.now()), local['user_id']))
        conn.commit()
    finally:
        conn.close()

def install(runtime):
    core.R = runtime
    app = core.R['app']

    @app.get('/api/pricing')
    def pricing():
        if core.R['waitlist_mode']():
            return {'plans':[{'key':'free','label':'Free preview','price_minor':0,'comments':5,'account_required':False}],
                    'checkout_enabled':False,'launch_mode':'waitlist','policy_version':core.POLICY_VERSION}
        return {'plans': core.public_catalog(), 'unit': 'matched opportunities, not guaranteed buyers', 'policy_version': core.POLICY_VERSION, 'checkout_enabled': bool(core.os.getenv('RAZORPAY_KEY_ID') and core.os.getenv('RAZORPAY_KEY_SECRET') and (core.os.getenv('YOUTUBE_USE_CASE_APPROVED') == 'true') and (core.os.getenv('PRICING_UNIT_ECONOMICS_VERIFIED') == 'true'))}

    @app.post('/api/billing/checkout')
    def checkout(body: core.Checkout, authorization: str=core.Header(None)):
        user = core.R['get_current_user'](authorization)
        if core.os.getenv('YOUTUBE_USE_CASE_APPROVED') != 'true' or core.os.getenv('PRICING_UNIT_ECONOMICS_VERIFIED') != 'true':
            raise core.HTTPException(503, 'Paid launch is not enabled; no charge has been made')
        if core.plan_of(user['id'])['key'] in ('starter', 'pro'):
            raise core.HTTPException(409, 'Your paid period is still active; contact support for a plan change')
        plan_id = core.os.getenv('RAZORPAY_PLAN_' + body.plan.upper(), '')
        if not plan_id:
            raise core.HTTPException(503, 'This billing plan has not been configured')
        provider = core.gateway('GET', 'plans/' + plan_id)
        if provider.get('period') != 'monthly' or provider.get('interval') != 1 or provider.get('item', {}).get('amount') != core.PUBLIC_PLANS[body.plan]['price_minor'] or (provider.get('item', {}).get('currency') != 'INR'):
            raise core.HTTPException(503, 'Provider plan price does not match the published offer')
        conn = core.R['get_db']()
        try:
            existing = conn.execute("SELECT id FROM billing_subscriptions WHERE user_id=? AND status IN ('creating','created','authenticated','active','pending')", (user['id'],)).fetchone()
        finally:
            conn.close()
        if existing:
            raise core.HTTPException(409, 'A subscription already exists; manage or cancel it before starting another')
        reservation = 'creating_' + core.secrets.token_hex(16)
        conn = core.R['get_db']()
        try:
            try:
                conn.execute('INSERT INTO billing_subscriptions VALUES(?,?,?,?,?)', (reservation, user['id'], body.plan, 'creating', core.iso(core.now())))
                conn.commit()
            except Exception:
                raise core.HTTPException(409, 'A checkout is already being prepared; contact support if it does not complete')
        finally:
            conn.close()
        subscription = core.gateway('POST', 'subscriptions', {'plan_id': plan_id, 'quantity': 1, 'total_count': 120, 'customer_notify': False, 'notes': {'user_id': str(user['id']), 'request_id': reservation}})
        sid = subscription.get('id', '')
        url = subscription.get('short_url', '')
        if not core.re.fullmatch('sub_[A-Za-z0-9]+', sid) or core.urlparse(url).scheme != 'https' or core.urlparse(url).hostname not in ('rzp.io', 'razorpay.com'):
            raise core.HTTPException(502, 'Provider returned an invalid checkout link')
        conn = core.R['get_db']()
        try:
            conn.execute("UPDATE billing_subscriptions SET id=?,status='created' WHERE id=?", (sid, reservation))
            conn.commit()
        finally:
            conn.close()
        return {'checkout_url': url, 'subscription_id': sid}

    @app.post('/api/billing/webhook')
    async def webhook(request: core.Request):
        raw = await request.body()
        secret = core.os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
        if not secret:
            raise core.HTTPException(503, 'Webhook verification is not configured')
        signature = request.headers.get('x-razorpay-signature', '')
        if not core.hmac.compare_digest(core.hmac.new(secret.encode(), raw, core.hashlib.sha256).hexdigest(), signature):
            raise core.HTTPException(401, 'Invalid webhook signature')
        if len(raw) > 100000:
            raise core.HTTPException(413, 'Webhook too large')
        try:
            data = core.json.loads(raw)
        except ValueError:
            raise core.HTTPException(400, 'Invalid JSON')
        event_id = request.headers.get('x-razorpay-event-id', '')
        if not event_id:
            raise core.HTTPException(400, 'Missing event identity')
        digest = core.hashlib.sha256(raw).hexdigest()
        conn = core.R['get_db']()
        try:
            existing = conn.execute('SELECT payload_hash FROM billing_events WHERE id=?', (event_id,)).fetchone()
        finally:
            conn.close()
        if existing:
            if existing[0] != digest:
                raise core.HTTPException(409, 'Event identity reused with different contents')
            return {'ok': True, 'duplicate': True}
        entity = data.get('payload', {}).get('subscription', {}).get('entity', {})
        sid = entity.get('id', '')
        if not core.re.fullmatch('sub_[A-Za-z0-9]+', sid):
            raise core.HTTPException(400, 'Missing subscription')
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(core.apply_subscription, sid)
        conn = core.R['get_db']()
        try:
            conn.execute('INSERT OR IGNORE INTO billing_events VALUES(?,?,?)', (event_id, digest, core.iso(core.now())))
            conn.commit()
        finally:
            conn.close()
        return {'ok': True}

    @app.post('/api/billing/cancel')
    def cancel(authorization: str=core.Header(None)):
        user = core.R['get_current_user'](authorization)
        conn = core.R['get_db']()
        try:
            row = conn.execute("SELECT id FROM billing_subscriptions WHERE user_id=? AND status IN ('active','authenticated','pending','created') ORDER BY created_at DESC LIMIT 1", (user['id'],)).fetchone()
        finally:
            conn.close()
        if not row:
            raise core.HTTPException(404, 'No active subscription')
        core.gateway('POST', 'subscriptions/' + row['id'] + '/cancel', {'cancel_at_cycle_end': 1})
        core.apply_subscription(row['id'])
        return {'ok': True, 'message': 'Cancellation requested for the end of the paid period'}

    @app.post('/api/legal/accept')
    def accept(body: core.Consent, authorization: str=core.Header(None)):
        user = core.R['get_current_user'](authorization)
        if not body.accepted or body.version != core.POLICY_VERSION:
            raise core.HTTPException(400, 'Accept the current policies to continue')
        conn = core.R['get_db']()
        try:
            conn.execute('INSERT OR REPLACE INTO policy_acceptance VALUES(?,?,?)', (user['id'], core.POLICY_VERSION, core.iso(core.now())))
            conn.commit()
        finally:
            conn.close()
        return core.consent_response()

    @app.get('/api/legal/status')
    def consent_status(authorization: str=core.Header(None)):
        user = core.R['get_current_user'](authorization)
        conn = core.R['get_db']()
        try:
            row = conn.execute('SELECT 1 FROM policy_acceptance WHERE user_id=? AND version=?', (user['id'], core.POLICY_VERSION)).fetchone()
        finally:
            conn.close()
        return {'version': core.POLICY_VERSION, 'accepted': bool(row)}
