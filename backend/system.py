"""System: focused API/service functions."""
from backend import runtime as core
from psycopg import Error as DatabaseError

def get_db():
    return core.database.connect(sqlite_path=core.DB_PATH)

@core.app.middleware('http')
async def add_security_headers(request: core.Request, call_next):
    public_paths={'/api/health','/api/auth/config','/api/pricing','/api/free-preview','/api/legal/accept-public','/api/waitlist'}
    if (core.waitlist_mode() and request.url.path.startswith('/api/')
            and request.url.path not in public_paths
            and request.url.path not in {'/api/account/delete','/api/billing/webhook'}
            and not request.url.path.startswith('/api/admin/')):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'This feature is coming soon. Join the waitlist for launch updates.'},status_code=403)
    if (getattr(core.app.state,'startup_error',None)
            and request.url.path.startswith('/api/')
            and request.url.path not in {'/api/health','/api/auth/config','/api/pricing','/api/waitlist','/api/free-preview','/api/legal/accept-public'}):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Application setup is incomplete. Please contact support.'},status_code=503)
    try:
        core.commerce.protect_request(request)
    except core.HTTPException as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
    except (RuntimeError,DatabaseError):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'This service is temporarily unavailable. Please try again later.'},status_code=503)
    token = core._API_CONTEXT.set({})
    try:
        response = await call_next(request)
    finally:
        core._API_CONTEXT.reset(token)
    device = request.state.trial_device
    response.set_cookie('cm_trial_device', device + '.' + core.commerce.identity_hash('device-cookie:' + device), max_age=31536000, httponly=True, samesite='lax', secure=core.os.getenv('APP_ENV') == 'production')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@core.app.get('/api/health')
def health_check(response: core.Response=None):
    sb_url, sb_key = core.supabase_config()
    try:
        conn = core.get_db()
        conn.execute('SELECT 1').fetchone()
        ws_count = conn.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0]
        lead_count = conn.execute('SELECT COUNT(*) FROM leads WHERE score>=40').fetchone()[0]
        conn.close()
        db_status = 'connected'
    except Exception as e:
        ws_count, lead_count = (0, 0)
        db_status = 'unavailable'
    if getattr(core.app.state,'startup_error',None):db_status='setup_required'
    if response is not None and db_status!='connected':response.status_code=503
    return {'status': 'ok' if db_status == 'connected' else 'degraded', 'version': '1.0.0', 'db': db_status, 'workspaces_count': ws_count, 'leads_count': lead_count, 'scheduler': core.scheduler.running, 'supabase_configured': bool(sb_url and sb_key), 'youtube_configured': bool(core.YT), 'gemini_configured': bool(core.GM), 'timestamp': core.datetime.now(core.timezone.utc).isoformat()}

@core.app.get('/')
def home():
    return core.FileResponse(core.FRONTEND_DIR / 'index.html')

def commercial_startup():
    core.commerce.production_preflight()
    if core.database.is_postgres():
        core.database.verify_schema()
    core.__dict__['_COMMERCIAL_READY'] = True
    core.app.state.startup_error=None


@core.app.on_event('startup')
def http_startup():
    # Public assets can load while setup is repaired. Private APIs fail closed.
    # The standalone worker calls commercial_startup() directly and still fails fast.
    try:core.commercial_startup()
    except (RuntimeError,DatabaseError) as error:
        core.__dict__['_COMMERCIAL_READY']=False
        core.app.state.startup_error='setup_required'
        core.logger.error('Application setup failed (%s); private API requests are disabled',type(error).__name__)

@core.app.on_event('shutdown')
def shutdown():
    core.__dict__['_COMMERCIAL_READY'] = False
    if core.scheduler.running:
        core.scheduler.shutdown(wait=False)
