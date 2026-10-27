"""Real Postgres integration checks, enabled only against an explicit loopback test DB."""
import json,os
from urllib.parse import urlparse
from unittest.mock import patch
import pytest
import psycopg
from fastapi import HTTPException
from backend import runtime as app,database
from backend.auth import provision_supabase_user
from scripts.manage_database import apply_schema,import_sqlite


@pytest.fixture
def postgres(monkeypatch):
    url=os.getenv('TEST_SUPABASE_DB_URL')
    if not url:pytest.skip('Set TEST_SUPABASE_DB_URL to the disposable loopback database')
    parsed=urlparse(url)
    assert parsed.hostname in ('localhost','127.0.0.1') and parsed.port==55438,'Only the isolated test database is permitted'
    monkeypatch.setenv('DATA_BACKEND','supabase');monkeypatch.setenv('SUPABASE_DB_URL',url)
    monkeypatch.setenv('PGSSLMODE','disable');monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('SUPABASE_URL','https://auth.example.test');monkeypatch.setenv('SUPABASE_ANON_KEY','public-test-key')
    with psycopg.connect(url,autocommit=True) as conn:
        for role in ('anon','authenticated'):
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():conn.execute('CREATE ROLE '+role)
    apply_schema();apply_schema()
    conn=database.connect()
    tables=[r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='app_private' AND tablename!='schema_version'")]
    conn.connection.execute('TRUNCATE '+','.join('app_private.'+table for table in tables)+' RESTART IDENTITY');conn.commit();conn.close()
    return url


def profile():
    return provision_supabase_user('founder@example.test','Founder','11111111-1111-1111-1111-111111111111')['user']


def test_complete_schema_is_private_repeatable_and_browser_roles_have_no_access(postgres):
    database.verify_schema();conn=database.connect()
    count=conn.execute("SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app_private' AND c.relkind='r' AND c.relrowsecurity").fetchone()[0]
    assert count==23
    assert not conn.execute("SELECT has_schema_privilege('anon','app_private','USAGE')").fetchone()[0]
    assert not conn.execute("SELECT has_table_privilege('authenticated','app_private.users','SELECT,INSERT,UPDATE,DELETE')").fetchone()[0]
    conn.close()


def test_supabase_identity_provisioning_is_idempotent_and_never_stores_passwords(postgres):
    first=profile();second=profile();assert first['id']==second['id']
    conn=database.connect();assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
    assert conn.execute('SELECT password_hash FROM users').fetchone()[0]==''
    assert conn.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0]==1;conn.close()
    with pytest.raises(HTTPException):provision_supabase_user('founder@example.test','Attacker','22222222-2222-2222-2222-222222222222')


def test_product_and_evidence_scoring_write_directly_to_postgres(postgres):
    user=profile()
    with patch.object(app,'get_current_user',return_value=user):
        ws=app.add_ws(app.WS(name='Tool',pitch='Lead scoring for small software founders'),authorization='Bearer verified')
    conn=database.connect();row=conn.execute('SELECT * FROM workspaces WHERE id=?',(ws['id'],)).fetchone()
    comment={'id':'real-comment','vid':'video','text':'Price?','author':'Buyer'}
    result={'results':[{'i':0,'score':88,'buyer_type':'buyer','feature':'Lead scoring','quote':'Price?','reason':'Price request'}]}
    with patch.object(app,'gem',return_value=result):app.score_pool(row,[comment],conn)
    saved=conn.execute('SELECT * FROM leads WHERE workspace_id=?',(ws['id'],)).fetchone()
    assert saved['score']==88 and saved['text']=='Price?' and saved['evidence']['quote']=='Price?'
    conn.close()


def test_credit_reservation_and_policy_upserts_are_transactional_on_postgres(postgres):
    user=profile();app.commerce.claim_trial(user['id'])
    token,n=app.commerce.reserve_analysis(user['id'],149);assert n==149
    other,n=app.commerce.reserve_analysis(user['id'],20);assert n==1
    with pytest.raises(HTTPException):app.commerce.reserve_analysis(user['id'],1)
    app.commerce.settle_analysis(other,False)
    conn=database.connect();assert app.commerce.remaining_analysis(conn,user['id'])==1
    conn.execute('INSERT OR REPLACE INTO policy_acceptance VALUES(?,?,?)',(user['id'],'v1','first'));conn.commit()
    conn.execute('INSERT OR REPLACE INTO policy_acceptance VALUES(?,?,?)',(user['id'],'v1','second'));conn.commit()
    assert conn.execute('SELECT accepted_at FROM policy_acceptance').fetchone()[0]=='second';conn.close()
    app.commerce.rate_limit('test','same-person',1,3600)
    with pytest.raises(HTTPException):app.commerce.rate_limit('test','same-person',1,3600)


def test_only_verified_supabase_tokens_are_accepted(postgres):
    import httpx
    confirmed={'id':'11111111-1111-1111-1111-111111111111','email':'founder@example.test','email_confirmed_at':'2026-10-27T00:00:00Z','user_metadata':{'plan':'unlimited'}}
    with patch.object(app,'_sb_get',return_value=httpx.Response(200,json=confirmed)):
        assert app.get_current_user('Bearer supabase-session')['email']=='founder@example.test'
    assert app.commerce.plan_of(1)['key']=='free'  # user metadata cannot grant a paid/admin plan
    with patch.object(app,'_sb_get',return_value=httpx.Response(200,json=confirmed|{'email_confirmed_at':None})):
        with pytest.raises(HTTPException):app.get_current_user('Bearer unconfirmed')
    with patch.object(app,'_sb_get',return_value=httpx.Response(401,json={})):
        with pytest.raises(HTTPException):app.get_current_user('Bearer '+app.create_access_token(1,'founder@example.test'))


def test_queue_ownership_and_outcomes_work_on_postgres(postgres):
    user=profile()
    with patch.object(app,'get_current_user',return_value=user):
        wid=app.add_ws(app.WS(name='Queue',pitch='Lead scoring for small software founders'),authorization='Bearer verified')['id']
    jid,rid=app.reserve_search(user['id'],wid,'auto',50)
    conn=database.connect();assert conn.execute('SELECT user_id FROM jobs WHERE id=?',(jid,)).fetchone()[0]==user['id']
    lid=conn.execute("INSERT INTO leads(workspace_id,comment_id,text,score,unlocked) VALUES(?,'source','Price?',90,1)",(wid,)).lastrowid;conn.commit();conn.close()
    with patch.object(app,'get_current_user',return_value=user):
        app.set_outcome(lid,app.Outcome(stage='contacted'),authorization='Bearer verified')
        assert app.workspace_metrics(wid,authorization='Bearer verified')['funnel']['contacted']==1


def test_import_preserves_records_without_changing_source_database(postgres,tmp_path):
    import sqlite3,hashlib
    path=tmp_path/'legacy.db';conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT,password_hash TEXT,created_at TEXT,plan TEXT,name TEXT,supabase_uid TEXT)')
    conn.execute("INSERT INTO users VALUES(7,'legacy@example.test','old-password-hash','2026-10-01','free','Legacy','')");conn.commit();conn.close()
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    assert import_sqlite(path)['users']==1
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    conn=database.connect();assert conn.execute('SELECT id FROM users').fetchone()[0]==7
    assert conn.execute('SELECT password_hash FROM users').fetchone()[0]==''
    next_id=conn.execute("INSERT INTO users(email) VALUES('next@example.test')").lastrowid;assert next_id>7;conn.commit();conn.close()
