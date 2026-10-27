from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import runtime as core
from backend import analytics

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'DB_PATH',str(tmp_path/'analytics.db'))
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('PUBLIC_LAUNCH_MODE','waitlist')
    monkeypatch.setattr(core.app.state,'startup_error',None,raising=False)
    core.init_db()
    return TestClient(core.app)

def rows():
    c=core.get_db()
    try:return [dict(row) for row in c.execute('SELECT * FROM site_usage_daily').fetchall()]
    finally:c.close()

def test_page_views_reuse_browser_cookie_and_ignore_assets(client):
    assert client.get('/').status_code==200
    assert client.get('/').status_code==200
    assert client.get('/assets/app.js').status_code==200
    data=rows();assert len(data)==1
    assert data[0]['page_views']==2 and data[0]['preview_attempts']==0
    assert len(data[0]['visitor_hash'])==64
    assert client.get('/api/analytics').status_code==403

def test_server_counts_results_empty_errors_and_rate_rejection(client):
    client.get('/')
    comment={'id':'c1','author':'Buyer','text':'Price?','published_at':'2026-10-27T01:00:00Z'}
    with patch.object(core,'video_ids',return_value=['abcdefghijk']),patch.object(core,'comments',return_value=[comment]),patch.object(core,'gem',return_value={'results':[{'i':0,'buyer_type':'buyer','direct_match':True,'intent':'purchase','need':'Requests pricing','quote':'Price?','feature':'lead scoring','reason':'Example assessed fit.'}]}):
        r=client.post('/api/free-preview',json={'product':{'description':'A tool that offers lead scoring for small software founders.','customer':'Small software founders'},'query':'private search'})
        assert r.status_code==200 and len(r.json()['leads'])==1
    with patch.object(core,'video_ids',return_value=[]),patch.object(core,'yt',return_value={'items':[]}):
        assert client.post('/api/free-preview',json={'product':{'description':'A tool that offers lead scoring for small software founders.','customer':'Small software founders'},'query':'nothing'}).status_code==200
    with patch.object(core,'video_ids',return_value=['abcdefghijk']),patch.object(core,'comments',side_effect=HTTPException(503,'Unavailable')):
        assert client.post('/api/free-preview',json={'product':{'description':'A tool that offers lead scoring for small software founders.','customer':'Small software founders'},'query':'test'}).status_code==503
    assert client.post('/api/free-preview',json={'product':{'description':'A tool that offers lead scoring for small software founders.','customer':'Small software founders'},'query':'test'}).status_code==429
    data=rows()[0]
    assert data['preview_attempts']==4
    assert data['previews_with_results']==1 and data['empty_previews']==1
    assert data['preview_errors']==2 and data['comments_returned']==1
    assert 'private search' not in str(data) and 'Buyer' not in str(data)

def test_tracking_failure_does_not_break_homepage(client):
    with patch.object(core,'get_db',side_effect=RuntimeError('private secret')):
        assert client.get('/').status_code==200

def test_old_counters_are_removed_on_next_visit(client):
    c=core.get_db()
    c.execute("INSERT INTO site_usage_daily(day,visitor_hash,page_views) VALUES('2000-01-01','expired',1)")
    c.commit();c.close()
    client.get('/')
    assert all(row['day']!='2000-01-01' for row in rows())

def test_public_ai_capacity_does_not_consume_the_whole_paid_pool(client,monkeypatch):
    monkeypatch.setenv('PREVIEW_DAILY_AI_REQUEST_BUDGET','1')
    token=core._API_CONTEXT.set({})
    try:
        core.begin_api_call('gemini','test-model')
        with pytest.raises(HTTPException) as exc:core.begin_api_call('gemini','test-model')
        assert exc.value.status_code==429
        with patch.object(core.commerce,'funding_class',return_value='paid'):
            assert core.begin_api_call('gemini','test-model')
    finally:core._API_CONTEXT.reset(token)
