"""Commercial boundaries tested against disposable SQLite and a mocked payment provider."""
import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import runtime as app
from backend import commercial as c


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB_PATH',str(tmp_path/'commercial.db'))
    for key in ('SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','YOUTUBE_USE_CASE_APPROVED','PRICING_UNIT_ECONOMICS_VERIFIED'):
        monkeypatch.setenv(key,'')
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('JOB_EXECUTION_MODE','inline')
    app.init_db()
    yield


def user(email='buyer@example.test',plan='free'):
    conn=app.get_db()
    uid=conn.execute('INSERT INTO users(email,password_hash,plan,billing_start,billing_end) VALUES(?,?,?,?,?)',
        (email,'',plan,c.iso(c.now()),c.iso(c.next_month(c.now())))).lastrowid
    conn.commit();conn.close()
    return uid,'Bearer '+app.create_access_token(uid,email)


def endpoint(path):
    return next(route.endpoint for route in app.app.routes if getattr(route,'path',None)==path)


def test_public_catalog_and_disabled_checkout():
    plans=endpoint('/api/pricing')()
    assert [p['price_minor'] for p in plans['plans']]==[0,49900,99900]
    assert not plans['checkout_enabled']
    uid,auth=user()
    with pytest.raises(HTTPException) as exc:endpoint('/api/billing/checkout')(c.Checkout(plan='starter'),auth)
    assert exc.value.status_code==503


def test_paid_period_expires_without_automatic_renewal():
    uid,auth=user(plan='starter')
    start=c.now();assert c.plan_of(uid)['key']=='starter'
    with patch.object(c,'now',return_value=c.next_month(start)+timedelta(seconds=5)):
        assert c.plan_of(uid)['key']=='free'


def test_analysis_reservations_release_on_failure_and_reset_only_with_period():
    uid,_=user(plan='starter')
    first,n=c.reserve_analysis(uid,1990);assert n==1990
    second,n=c.reserve_analysis(uid,100);assert n==10
    with pytest.raises(HTTPException):c.reserve_analysis(uid,1)
    c.settle_analysis(second,False)
    retry,n=c.reserve_analysis(uid,50);assert n==10
    c.settle_analysis(first,True);c.settle_analysis(retry,True)
    conn=app.get_db()
    conn.execute('UPDATE users SET billing_start=?,billing_end=? WHERE id=?',
        (c.iso(c.now()+timedelta(seconds=1)),c.iso(c.next_month(c.now())),uid));conn.commit()
    assert c.remaining_analysis(conn,uid)==2000
    conn.close()


def test_trial_alias_and_device_cannot_claim_second_allowance():
    first,_=user('my.name+one@gmail.com');second,_=user('myname+two@googlemail.com')
    c.claim_trial(first)
    with pytest.raises(HTTPException):c.claim_trial(second)
    third,_=user('other@example.test')
    request=SimpleNamespace(state=SimpleNamespace(trial_device='same-browser'))
    c.claim_trial(first,request)
    with pytest.raises(HTTPException):c.claim_trial(third,request)


def test_trial_expiry_and_email_verification(monkeypatch):
    uid,_=user()
    # Production storage cannot fall back to SQLite, even for a verified email.
    monkeypatch.setenv('APP_ENV','production')
    with pytest.raises(RuntimeError,match='SQLite is restricted'):app.get_db()
    monkeypatch.setenv('APP_ENV','test')
    c.verified_email(uid,True);c.claim_trial(uid)
    with patch.object(c,'now',return_value=c.now()+timedelta(days=8)):
        with pytest.raises(HTTPException):c.claim_trial(uid)


def test_products_are_shared_account_allowance():
    uid,auth=user()
    app.add_ws(app.WS(name='First',pitch='A meaningful product description'),authorization=auth)
    with pytest.raises(HTTPException):app.add_ws(app.WS(name='Second',pitch='Another meaningful product description'),authorization=auth)
    conn=app.get_db();conn.execute("UPDATE users SET plan='pro' WHERE id=?",(uid,));conn.commit();conn.close()
    app.add_ws(app.WS(name='Second',pitch='Another meaningful product description'),authorization=auth)
    with pytest.raises(HTTPException):app.add_ws(app.WS(name='Third',pitch='Third meaningful product description'),authorization=auth)


def test_request_throttle_scopes_do_not_spend_another_users_limit():
    c.rate_limit('test','one',1,3600)
    with pytest.raises(HTTPException):c.rate_limit('test','one',1,3600)
    c.rate_limit('test','two',1,3600)


def subscription(uid,plan='starter'):
    conn=app.get_db();conn.execute('INSERT INTO billing_subscriptions VALUES(?,?,?,?,?)',('sub_test',uid,plan,'created',c.iso(c.now())));conn.commit();conn.close()
    return dict(id='sub_test',plan_id='plan_starter',quantity=1,status='active',paid_count=1,
        current_start=int(c.now().timestamp()),current_end=int(c.next_month(c.now()).timestamp()))


def test_only_paid_verified_provider_period_grants_access(monkeypatch):
    uid,_=user();state=subscription(uid);monkeypatch.setenv('RAZORPAY_PLAN_STARTER','plan_starter')
    with patch.object(c,'gateway',return_value=state|{'paid_count':0}):c.apply_subscription('sub_test')
    assert c.plan_of(uid)['key']=='free'
    with patch.object(c,'gateway',return_value=state):c.apply_subscription('sub_test');c.apply_subscription('sub_test')
    assert c.plan_of(uid)['key']=='starter'
    with patch.object(c,'gateway',return_value=state|{'plan_id':'wrong'}):
        with pytest.raises(HTTPException):c.apply_subscription('sub_test')
    with patch.object(c,'gateway',return_value=state|{'status':'cancelled'}):c.apply_subscription('sub_test')
    assert c.plan_of(uid)['key']=='starter'  # paid remainder survives cancellation


def test_signed_webhook_is_idempotent_and_rejects_tampering(monkeypatch):
    uid,_=user();state=subscription(uid)
    monkeypatch.setenv('RAZORPAY_PLAN_STARTER','plan_starter');monkeypatch.setenv('RAZORPAY_WEBHOOK_SECRET','test-secret')
    raw=json.dumps({'event':'subscription.charged','payload':{'subscription':{'entity':{'id':'sub_test'}}}}).encode()
    headers={'x-razorpay-event-id':'event1','x-razorpay-signature':hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()}
    client=TestClient(app.app)
    with patch.object(c,'gateway',return_value=state) as gateway:
        assert client.post('/api/billing/webhook',content=raw,headers=headers).status_code==200
        assert client.post('/api/billing/webhook',content=raw,headers=headers).json()['duplicate']
        assert gateway.call_count==1
        assert client.post('/api/billing/webhook',content=raw+b' ',headers=headers).status_code==401


def test_checkout_checks_price_and_prevents_duplicate_subscription(monkeypatch):
    uid,auth=user()
    for name in ('YOUTUBE_USE_CASE_APPROVED','PRICING_UNIT_ECONOMICS_VERIFIED'):monkeypatch.setenv(name,'true')
    monkeypatch.setenv('RAZORPAY_PLAN_STARTER','plan_starter')
    provider={'period':'monthly','interval':1,'item':{'amount':49900,'currency':'INR'}}
    with patch.object(c,'gateway',side_effect=[provider,{'id':'sub_new','short_url':'https://rzp.io/test'}]):
        assert endpoint('/api/billing/checkout')(c.Checkout(plan='starter'),auth)['subscription_id']=='sub_new'
    with patch.object(c,'gateway',return_value=provider):
        with pytest.raises(HTTPException) as exc:endpoint('/api/billing/checkout')(c.Checkout(plan='starter'),auth)
    assert exc.value.status_code==409
    other,auth=user('other@example.test')
    with patch.object(c,'gateway',return_value=provider|{'item':{'amount':29900,'currency':'INR'}}):
        with pytest.raises(HTTPException):endpoint('/api/billing/checkout')(c.Checkout(plan='starter'),auth)


def test_retention_failure_scrubs_expired_text_and_source_is_hidden(monkeypatch):
    conn=app.get_db();conn.execute("INSERT INTO leads(workspace_id,comment_id,video_id,text,retrieved_at) VALUES(1,'gone','video','private old text',?)",(c.iso(c.now()-timedelta(days=23)),));conn.commit();conn.close()
    with patch.object(app,'yt',side_effect=RuntimeError('offline')):result=c.refresh_sources()
    assert result['expired_removed']==1
    conn=app.get_db();row=conn.execute('SELECT * FROM leads').fetchone();conn.close()
    assert row['text']=='' and not c.source_visible(row)


def test_backup_restores_commercial_entitlements(tmp_path):
    import sqlite3
    uid,_=user(plan='pro');c.claim_trial(uid)
    backup=c.database_backup();conn=sqlite3.connect(backup)
    assert conn.execute('SELECT plan FROM users WHERE id=?',(uid,)).fetchone()[0]=='pro'
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='match_grants'").fetchone()
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok';conn.close()


def test_account_deletion_invalidates_old_tokens(monkeypatch):
    uid,auth=user();conn=app.get_db()
    conn.execute("INSERT INTO deletion_requests VALUES(?,?,'pending','')",(uid,c.iso(c.now())));conn.commit();conn.close()
    monkeypatch.setitem(c.R,'_COMMERCIAL_READY',True)
    c.process_deletions()
    with pytest.raises(HTTPException):app.get_current_user(auth)
    conn=app.get_db();row=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();conn.close()
    assert row['deleted_at'] and row['email'].endswith('@deleted.invalid')


def test_monthly_matches_do_not_recharge_old_results():
    uid,auth=user(plan='starter')
    wid=app.add_ws(app.WS(name='Test',pitch='A meaningful product description'),authorization=auth)['id']
    conn=app.get_db()
    conn.executemany('INSERT INTO leads(workspace_id,comment_id,text,score) VALUES(?,?,?,90)',
        [(wid,str(i),'source comment') for i in range(201)])
    conn.commit();c.unlock_top_leads(conn,uid,wid)
    assert conn.execute('SELECT COUNT(*) FROM leads WHERE unlocked=1').fetchone()[0]==200
    new_start=c.iso(c.now()+timedelta(seconds=1))
    conn.execute('UPDATE users SET billing_start=? WHERE id=?',(new_start,uid));conn.commit()
    c.unlock_top_leads(conn,uid,wid)
    assert conn.execute('SELECT COUNT(*) FROM match_grants WHERE period_key=?',(new_start,)).fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM leads WHERE unlocked=1').fetchone()[0]==201
    conn.close()


def test_queue_is_durable_and_worker_admission_is_bounded(monkeypatch):
    uid,auth=user();wid=app.add_ws(app.WS(name='Queued',pitch='A meaningful product description'),authorization=auth)['id']
    jid,rid=app.reserve_search(uid,wid,'auto',50)
    monkeypatch.setenv('JOB_EXECUTION_MODE','queued');monkeypatch.setenv('MAX_ACTIVE_JOBS','1')
    c.submit_job(app.run_auto_job,jid,wid,80,2,run_id=rid,n_queries=1)
    app.init_db()  # queued payload survives startup
    monkeypatch.setitem(c.R,'_COMMERCIAL_READY',True)
    with patch.object(c.threading,'Thread') as thread:
        c.work_queue();c.work_queue()
        assert thread.call_count==1
    conn=app.get_db();assert conn.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='running';conn.close()
    app.init_db()  # interrupted running payload becomes resumable queued work
    conn=app.get_db();assert conn.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='queued';conn.close()


def test_old_subscription_event_cannot_revoke_newer_paid_contract(monkeypatch):
    uid,_=user(plan='pro');state=subscription(uid)
    monkeypatch.setenv('RAZORPAY_PLAN_STARTER','plan_starter')
    conn=app.get_db()
    conn.execute("UPDATE billing_subscriptions SET status='cancelled' WHERE id='sub_test'")
    conn.execute("INSERT INTO billing_subscriptions VALUES('sub_new',?,'pro','active',?)",(uid,c.iso(c.now()+timedelta(seconds=1))))
    conn.commit();conn.close()
    with patch.object(c,'gateway',return_value=state|{'status':'expired'}):c.apply_subscription('sub_test')
    assert c.plan_of(uid)['key']=='pro'


def test_saved_reassessment_does_not_invent_a_retrieval_timestamp():
    uid,auth=user()
    wid=app.add_ws(app.WS(name='Saved',pitch='A meaningful product description'),authorization=auth)['id']
    conn=app.get_db();ws=conn.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone()
    pool=[{'id':'legacy','vid':'video','text':'Price?','retrieved_at':''}]
    with patch.object(app,'gem',return_value={'results':[]}):app.score_pool(ws,pool,conn)
    assert conn.execute("SELECT retrieved_at FROM leads WHERE comment_id='legacy'").fetchone()[0]==''
    conn.close()


def test_unknown_retrieval_date_is_scrubbed_after_failed_refresh():
    conn=app.get_db()
    conn.execute("INSERT INTO leads(workspace_id,comment_id,video_id,text,author,evidence) VALUES(1,'legacy-id','video-id','old private source','old author','{}')")
    conn.commit();conn.close()
    with patch.object(app,'yt',side_effect=RuntimeError('offline')):result=c.refresh_sources()
    assert result['expired_removed']==1
    conn=app.get_db();row=conn.execute('SELECT * FROM leads').fetchone();conn.close()
    assert row['comment_id'].startswith('expired:') and row['video_id']==''
    assert row['text']==row['author']=='' and row['retention_expired']==1


def test_failed_mirror_scrub_is_durable_and_retried(monkeypatch):
    conn=app.get_db()
    conn.execute("INSERT INTO leads(workspace_id,comment_id,video_id,text,retrieved_at) VALUES(1,'old-id','video','expired text',?)",(c.iso(c.now()-timedelta(days=23)),))
    conn.commit();conn.close()
    monkeypatch.setenv('SUPABASE_URL','https://mirror.example.test');monkeypatch.setenv('SUPABASE_ANON_KEY','test')
    with patch.object(app,'yt',side_effect=RuntimeError('offline')),patch.object(app,'sb_rest',return_value=None):c.refresh_sources()
    conn=app.get_db();assert conn.execute('SELECT COUNT(*) FROM lifecycle_sync').fetchone()[0]==1;conn.close()
    app.init_db()  # durable retry survives restart
    with patch.object(app,'sb_rest',return_value=[]) as remote:
        assert c.flush_source_sync()==1
    sent=remote.call_args.kwargs['json_body']
    assert sent['text']=='' and sent['video_id']=='' and sent['retention_expired']
    assert type(sent['retention_expired']) is int  # matches the deployed SQL column type
    conn=app.get_db();assert conn.execute('SELECT COUNT(*) FROM lifecycle_sync').fetchone()[0]==0;conn.close()


def test_refresh_changes_invalidate_previous_match_evidence():
    conn=app.get_db()
    conn.execute("INSERT INTO leads(workspace_id,comment_id,video_id,text,score,reason,reply,retrieved_at) VALUES(1,'edited','video','old request',90,'old reason','old reply',?)",(c.iso(c.now()-timedelta(days=21,hours=2)),))
    conn.commit();conn.close()
    comments={'items':[{'id':'edited','snippet':{'textOriginal':'No longer looking','authorDisplayName':'Buyer'}}]}
    videos={'items':[{'id':'video','snippet':{'title':'Source video'}}]}
    with patch.object(app,'yt',side_effect=[comments,videos]):c.refresh_sources()
    conn=app.get_db();row=conn.execute('SELECT * FROM leads').fetchone();conn.close()
    assert row['text']=='No longer looking' and row['score']==0 and row['reason']==row['reply']==''
    assert row['analysis_state']=='pending' and c.parse(row['retrieved_at'])>c.now()-timedelta(minutes=1)


def test_deferred_sync_cannot_restore_scrubbed_content(monkeypatch):
    uid,auth=user();wid=app.add_ws(app.WS(name='Deferred',pitch='A meaningful product description'),authorization=auth)['id']
    conn=app.get_db();conn.execute("INSERT INTO leads(workspace_id,comment_id,text) VALUES(?,'deferred','raw old text')",(wid,));conn.commit()
    row=conn.execute('SELECT * FROM leads').fetchone();conn.close()
    monkeypatch.setenv('SUPABASE_URL','https://mirror.example.test');monkeypatch.setenv('SUPABASE_ANON_KEY','test')
    with patch.object(app,'_run_sb_async') as deferred:app.sb_sync_leads_rows([row])
    conn=app.get_db();c.expire_source(conn,row);conn.commit();conn.close()
    with patch.object(app,'sb_rest') as remote:deferred.call_args.args[0]()
    remote.assert_not_called()


def test_exhausted_analysis_cannot_reserve_another_job():
    uid,auth=user();wid=app.add_ws(app.WS(name='Empty',pitch='A meaningful product description'),authorization=auth)['id']
    credit,_=c.reserve_analysis(uid,150);c.settle_analysis(credit,True)
    with pytest.raises(HTTPException) as exc:app.reserve_search(uid,wid,'auto',50)
    assert exc.value.status_code==403
    conn=app.get_db();assert conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==0;conn.close()


def test_supabase_session_cannot_bypass_pending_account_deletion():
    uid,_=user();conn=app.get_db()
    conn.execute("INSERT INTO deletion_requests VALUES(?,?,'pending','')",(uid,c.iso(c.now())));conn.commit();conn.close()
    with patch.object(app,'decode_token',return_value=None),patch.object(app,'verify_supabase_access_token',return_value={'id':uid,'email':'buyer@example.test'}):
        with pytest.raises(HTTPException) as exc:app.get_current_user('Bearer cloud-session')
    assert exc.value.status_code==401


def test_hourly_admission_does_not_scan_a_product_again_within_week(monkeypatch):
    uid,auth=user(plan='pro');app.add_ws(app.WS(name='Scheduled',pitch='A meaningful product description'),authorization=auth)
    monkeypatch.setitem(c.R,'_COMMERCIAL_READY',False)
    with patch.object(app,'run_auto_job') as run:
        app.scheduled_auto_run_all();app.scheduled_auto_run_all()
    assert run.call_count==1


def test_public_preview_rate_limit_survives_app_restart():
    client=TestClient(app.app)
    with patch.object(app,'comments',return_value=[]),patch.object(app,'yt',return_value={'items':[]}):
        for _ in range(3):client.post('/api/free-preview',json={'query':'test'})
        app.init_db()
        assert client.post('/api/free-preview',json={'query':'test'}).status_code==429


def test_render_preflight_requires_mounted_disk_and_contained_database(monkeypatch,tmp_path):
    for key in ('SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','SUPPORT_EMAIL','OPERATOR_NAME'):
        monkeypatch.setenv(key,'configured-test-value')
    monkeypatch.setenv('APP_ENV','production');monkeypatch.setenv('APP_URL','https://app.example.test')
    monkeypatch.setenv('RENDER','true');monkeypatch.setenv('JOB_EXECUTION_MODE','queued')
    monkeypatch.setenv('PERSISTENT_DISK_PATH',str(tmp_path))
    monkeypatch.setitem(c.R,'_configured_jwt_secret','private-test-value');monkeypatch.setitem(c.R,'ALLOWED_ORIGINS',['https://app.example.test'])
    with patch.object(c.os.path,'ismount',return_value=False):
        with pytest.raises(RuntimeError,match='mounted persistent disk'):c.production_preflight()
    with patch.object(c.os.path,'ismount',return_value=True):c.production_preflight()
    monkeypatch.setenv('PERSISTENT_DISK_PATH',str(tmp_path/'wrong'))
    with patch.object(c.os.path,'ismount',return_value=True):
        with pytest.raises(RuntimeError,match='DB_PATH beneath persistent disk'):c.production_preflight()


def test_free_queue_reservations_cannot_consume_paid_search_pool(monkeypatch):
    monkeypatch.setenv('TRIAL_DAILY_SEARCH_BUDGET','1')
    first,auth=user('first@example.test');wid=app.add_ws(app.WS(name='First',pitch='A meaningful product description'),authorization=auth)['id']
    app.reserve_search(first,wid,'auto',50)
    second,auth=user('second@example.test');wid=app.add_ws(app.WS(name='Second',pitch='A meaningful product description'),authorization=auth)['id']
    with pytest.raises(HTTPException) as exc:app.reserve_search(second,wid,'auto',50)
    assert exc.value.status_code==429
    paid,auth=user('paid@example.test',plan='starter');wid=app.add_ws(app.WS(name='Paid',pitch='A meaningful product description'),authorization=auth)['id']
    assert app.reserve_search(paid,wid,'auto',50)[0]


def test_alert_logs_do_not_keep_a_second_copy_of_comment_content(monkeypatch):
    uid,_=user()
    app.record_email_log('buyer@example.test','New match','raw public comment text',user_id=uid)
    conn=app.get_db();assert conn.execute('SELECT body FROM email_logs').fetchone()[0]==c.ALERT_LOG_BODY
    conn.execute("UPDATE email_logs SET body='historical source text'");conn.commit();conn.close()
    monkeypatch.setenv('SUPABASE_URL','https://mirror.example.test');monkeypatch.setenv('SUPABASE_ANON_KEY','test')
    with patch.object(app,'sb_rest',return_value=None):c.refresh_sources()
    conn=app.get_db()
    assert conn.execute('SELECT body FROM email_logs').fetchone()[0]==c.ALERT_LOG_BODY
    assert conn.execute('SELECT COUNT(*) FROM lifecycle_cleanup_tasks').fetchone()[0]==1;conn.close()
    with patch.object(app,'sb_rest',return_value=[]) as remote:c.flush_source_sync()
    assert remote.call_args.args[:2]==('PATCH','email_logs')
    assert remote.call_args.kwargs['json_body']['body']==c.ALERT_LOG_BODY


def test_verified_email_sync_matches_integer_sql_column(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://mirror.example.test');monkeypatch.setenv('SUPABASE_ANON_KEY','test')
    with patch.object(app,'sb_rest',return_value=[]) as remote:
        app.sb_sync_user_row({'id':2,'email':'test@example.test','email_verified':1},sync_now=True)
    assert type(remote.call_args.kwargs['json_body']['email_verified']) is int
