"""System: focused API/service functions."""
from backend import runtime as core

def get_db():
    return core.database.connect(sqlite_path=core.DB_PATH)

@core.app.middleware('http')
async def add_security_headers(request: core.Request, call_next):
    try:
        core.commerce.protect_request(request)
    except core.HTTPException as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
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
def health_check():
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
        db_status = f'error: {e}'
    return {'status': 'ok' if db_status == 'connected' else 'degraded', 'version': '1.0.0', 'db': db_status, 'workspaces_count': ws_count, 'leads_count': lead_count, 'scheduler': core.scheduler.running, 'supabase_configured': bool(sb_url and sb_key), 'youtube_configured': bool(core.YT), 'gemini_configured': bool(core.GM), 'timestamp': core.datetime.now(core.timezone.utc).isoformat()}

@core.app.get('/')
def home():
    return core.FileResponse(core.FRONTEND_DIR / 'index.html')

@core.app.on_event('startup')
def commercial_startup():
    core.commerce.production_preflight()
    if core.database.is_postgres():
        core.database.verify_schema()
    core.__dict__['_COMMERCIAL_READY'] = True

@core.app.on_event('shutdown')
def shutdown():
    core.__dict__['_COMMERCIAL_READY'] = False
    if core.scheduler.running:
        core.scheduler.shutdown(wait=False)
