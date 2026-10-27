"""Private first-party daily counters. No queries, comments, emails or raw IPs."""
from datetime import timedelta
from starlette.concurrency import run_in_threadpool
from backend import runtime as core


def record_usage(request, status, result_count=0):
    try:
        day=core.commerce.now().date().isoformat()
        device=getattr(request.state,'trial_device',None) or core.secrets.token_hex(16)
        visitor=core.commerce.identity_hash('analytics:'+day+':'+device)
        visit=int(request.method=='GET' and request.url.path=='/' and status==200)
        preview=int(request.method=='POST' and request.url.path=='/api/free-preview')
        success=int(preview and status==200 and result_count>0)
        empty=int(preview and status==200 and result_count==0)
        error=int(preview and status>=400)
        conn=core.get_db()
        try:
            conn.execute('''INSERT INTO site_usage_daily
                (day,visitor_hash,page_views,preview_attempts,previews_with_results,empty_previews,preview_errors,comments_returned)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(day,visitor_hash) DO UPDATE SET
                page_views=site_usage_daily.page_views+excluded.page_views,
                preview_attempts=site_usage_daily.preview_attempts+excluded.preview_attempts,
                previews_with_results=site_usage_daily.previews_with_results+excluded.previews_with_results,
                empty_previews=site_usage_daily.empty_previews+excluded.empty_previews,
                preview_errors=site_usage_daily.preview_errors+excluded.preview_errors,
                comments_returned=site_usage_daily.comments_returned+excluded.comments_returned''',
                (day,visitor,visit,preview,success,empty,error,result_count if success else 0))
            # Bounded retention, including on serverless deployments without a worker.
            cutoff=(core.commerce.now()-timedelta(days=90)).date().isoformat()
            conn.execute('DELETE FROM site_usage_daily WHERE day<?',(cutoff,))
            conn.commit()
        finally:conn.close()
    except Exception:
        # Analytics must never prevent a visitor from using the app.
        core.logger.warning('Usage tracking unavailable')


@core.app.middleware('http')
async def usage_tracking(request,call_next):
    tracked=(request.method=='GET' and request.url.path=='/') or (request.method=='POST' and request.url.path=='/api/free-preview')
    if not tracked:return await call_next(request)
    try:
        response=await call_next(request)
    except Exception:
        await run_in_threadpool(record_usage,request,500,0)
        raise
    await run_in_threadpool(record_usage,request,response.status_code,getattr(request.state,'preview_result_count',0))
    return response
