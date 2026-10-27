import pytest
from fastapi.testclient import TestClient
from backend import runtime as core

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'DB_PATH',str(tmp_path/'waitlist.db'))
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('PUBLIC_LAUNCH_MODE','waitlist')
    monkeypatch.setattr(core.app.state,'startup_error',None,raising=False)
    core.init_db()
    return TestClient(core.app)

def entry(**changes):
    return dict(email='Buyer@example.test',consent=True,policy_version=core.commerce.POLICY_VERSION,**changes)

def test_anonymous_waitlist_persists_once_without_creating_account(client):
    conn=core.get_db();before=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0];conn.close()
    for _ in range(2):assert client.post('/api/waitlist',json=entry()).status_code==200
    conn=core.get_db()
    assert conn.execute('SELECT COUNT(*) FROM waitlist').fetchone()[0]==1
    assert conn.execute('SELECT email FROM waitlist').fetchone()[0]=='buyer@example.test'
    assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==before
    conn.close()

def test_validation_honeypot_and_rate_limit(client):
    body=entry();body['consent']=False
    assert client.post('/api/waitlist',json=body).status_code==422
    body=entry();body['email']='invalid'
    assert client.post('/api/waitlist',json=body).status_code==422
    assert client.post('/api/waitlist',json=entry(website='bot')).status_code==200
    for _ in range(5):assert client.post('/api/waitlist',json=entry()).status_code==200
    assert client.post('/api/waitlist',json=entry()).status_code==429

def test_launch_closes_account_and_paid_routes(client):
    assert client.get('/api/workspaces').status_code==403
    assert client.post('/api/billing/checkout',json={'plan':'starter'}).status_code==403
    catalog=client.get('/api/pricing').json()
    assert catalog['checkout_enabled'] is False
    assert len(catalog['plans'])==1
