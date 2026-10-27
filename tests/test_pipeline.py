import time, json
import pytest
import sqlite3
import os
import re
from pydantic import ValidationError
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

from backend import runtime as app


def _matching_profile(**changes):
    values = dict(target_customer="Families ordering homemade pickles", problem="Need fresh homemade pickles",
                  delivery_scope="local", locations="Hyderabad only", languages="Telugu, English",
                  pricing="₹250 per jar", competitors="Local Pickle Shop", exclusions="Wholesalers",
                  limitations="No shipping outside Hyderabad")
    values.update(changes)
    return app.MatchingProfile(**values)


def test_profile_save_read_edit_and_legacy_update(tmp_path):
    app.DB_PATH = str(tmp_path / "profile.db")
    app.init_db()
    auth = "Bearer " + app.create_access_token(1, "founder@comment-money.local")
    profile = _matching_profile()
    saved = app.add_ws(app.WS(name="Pickles", pitch="Fresh homemade pickles for families", profile=profile), authorization=auth)
    assert next(w for w in app.list_ws(authorization=auth) if w["id"] == saved["id"])["profile"] == profile.model_dump()
    # Older clients omitting profile must not erase the owner's criteria.
    app.add_ws(app.WS(name="Pickles", pitch="Fresh homemade pickles for families"), authorization=auth)
    assert next(w for w in app.list_ws(authorization=auth) if w["id"] == saved["id"])["profile"]["locations"] == "Hyderabad only"
    app.add_ws(app.WS(name="Pickles", pitch="Fresh homemade pickles for families",
                      profile=_matching_profile(locations="Chennai only")), authorization=auth)
    assert next(w for w in app.list_ws(authorization=auth) if w["id"] == saved["id"])["profile"]["locations"] == "Chennai only"
    app.init_db()  # Migration is repeatable and preserves profiles.
    conn = app.get_db()
    assert app.workspace_profile(conn.execute("SELECT * FROM workspaces WHERE id=?", (saved["id"],)).fetchone())["locations"] == "Chennai only"
    conn.close()


@pytest.mark.parametrize("changes", [{"target_customer":"  "}, {"problem":""},
    {"delivery_scope":"anywhere-ish"}, {"locations":""}, {"languages":""}, {"pricing":"x" * 501}])
def test_profile_rejects_missing_or_invalid_criteria(changes):
    with pytest.raises(ValidationError):
        _matching_profile(**changes)


def test_profile_reaches_onboarding_and_scoring_without_invented_competitors(tmp_path):
    app.DB_PATH = str(tmp_path / "profile_prompts.db")
    app.init_db()
    auth = "Bearer " + app.create_access_token(1, "founder@comment-money.local")
    profile = _matching_profile()
    with patch("backend.runtime.gem", return_value={"pitch":"Fresh homemade pickles", "competitors":["Invented Brand"]}) as gem:
        result = app.onboard_suggest(app.Onboard(name="Pickles", about="Fresh homemade pickles", profile=profile), authorization=auth)
    assert "Hyderabad only" in gem.call_args.args[0]
    assert result["competitors"] == ["Local Pickle Shop"]
    assert result["profile"] == profile.model_dump()
    wid = app.add_ws(app.WS(name="Pickles", pitch="Fresh homemade pickles", profile=profile), authorization=auth)["id"]
    conn = app.get_db()
    ws = conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
    conn.close()
    comment = {"id":"profile-comment", "vid":"video", "title":"Pickles", "author":"Buyer",
               "text":"Where can I order homemade pickles for my family?"}
    with patch("backend.runtime.comments", return_value=[comment]), patch("backend.runtime.gem", return_value={"results":[]}) as gem:
        app.run_scan(ws, ["video"], 10)
    prompt = gem.call_args.args[0]
    assert "Hyderabad only" in prompt and "₹250 per jar" in prompt
    assert "Location unverified" in prompt and "Do not infer location" in prompt
    query = app.QUERY_PROMPT.format(name=ws["name"], pitch=app.matching_pitch(ws), signals="")
    assert "Local Pickle Shop" in query and "Telugu" in query


def test_profile_sync_uses_json_object():
    profile = _matching_profile().model_dump()
    with patch.dict(os.environ, {"SUPABASE_URL":"https://test.supabase.co", "SUPABASE_ANON_KEY":"anon"}), \
         patch("backend.runtime._run_sb_async") as sync:
        app.sb_sync_workspace_row({"id":1, "user_id":1, "name":"Pickles", "profile":json.dumps(profile)})
    assert sync.call_args.kwargs["json_body"]["profile"] == profile


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/workspaces", None),
    ("GET", "/api/auth/me", None),
    ("GET", "/api/leads?workspace_id=1", None),
    ("GET", "/api/job/1", None),
    ("GET", "/api/supabase/emails", None),
    ("GET", "/api/supabase/status", None),
    ("POST", "/api/supabase/sync", {}),
    ("POST", "/api/automation/trigger", {}),
    ("POST", "/api/auth/supabase-config", {
        "supabase_url": "https://attacker.supabase.co", "supabase_anon_key": "a" * 30}),
])
def test_private_routes_reject_guests(tmp_path, method, path, body):
    app.DB_PATH = str(tmp_path / "private.db")
    app.init_db()
    handlers = {
        "/api/workspaces": (app.list_ws, ()), "/api/auth/me": (app.me, ()),
        "/api/leads?workspace_id=1": (app.leads, (1,)), "/api/job/1": (app.get_job, (1,)),
        "/api/supabase/emails": (app.list_supabase_emails, ()),
        "/api/supabase/status": (app.supabase_status, ()),
        "/api/supabase/sync": (app.trigger_supabase_sync, ()),
        "/api/automation/trigger": (app.trigger_scheduled_now, ()),
        "/api/auth/supabase-config": (app.save_supabase_config, (app.SupabaseConfigUpdate(**body),)) if body and "supabase_url" in body else (None, ()),
    }
    handler, args = handlers[path]
    with pytest.raises(HTTPException) as exc:
        handler(*args, authorization=None)
    assert exc.value.status_code == 401


def test_job_and_email_tenant_isolation(tmp_path):
    app.DB_PATH = str(tmp_path / "tenants.db")
    app.init_db()
    owner = app.register(app.Register(email="owner@tenant.test", password="password123"))
    other = app.register(app.Register(email="other@tenant.test", password="password123"))
    uid = owner["user"]["id"]
    conn = app.get_db()
    jid = conn.execute("INSERT INTO jobs(user_id, result) VALUES (?, ?)",
                       (uid, '{"private":"owner only"}')).lastrowid
    conn.execute("INSERT INTO email_logs(user_id, subject) VALUES (?, 'private email')", (uid,))
    conn.commit()
    conn.close()
    auth = f"Bearer {other['token']}"
    with pytest.raises(HTTPException) as exc:
        app.get_job(jid, authorization=auth)
    assert exc.value.status_code == 404
    assert app.list_supabase_emails(authorization=auth) == []
    for handler in (app.trigger_supabase_sync, app.trigger_scheduled_now, app.supabase_status):
        with pytest.raises(HTTPException) as exc:
            handler(authorization=auth)
        assert exc.value.status_code == 403
    auth = f"Bearer {owner['token']}"
    assert app.get_job(jid, authorization=auth)["result"]["private"] == "owner only"
    assert len(app.list_supabase_emails(authorization=auth)) == 1


def test_sync_reports_remote_failure(tmp_path):
    app.DB_PATH = str(tmp_path / "sync_failure.db")
    app.init_db()
    with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co",
                                "SUPABASE_ANON_KEY": "anon-key",
                                "SUPABASE_SERVICE_ROLE_KEY": "service-key"}), \
         patch("httpx.request", return_value=MagicMock(status_code=500, content=b"error")):
        result = app.sync_all_to_supabase()
    assert result["ok"] is False
    assert result["pushed"]["users"] == 0
    assert result["errors"]


def test_database_sync_never_uses_public_key():
    with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co",
                                "SUPABASE_ANON_KEY": "public-key",
                                "SUPABASE_SERVICE_ROLE_KEY": ""}), patch("httpx.request") as request:
        assert app.sb_db_headers() == {}
        assert app.sync_all_to_supabase()["ok"] is False
        assert app.sb_rest("GET", "users") is None
        request.assert_not_called()


@pytest.mark.parametrize("public_key", ["postgresql://private-db", "sb_secret_private",
    app.jwt.encode({"role": "service_role"}, "test-secret-which-is-long-enough-123", algorithm="HS256")])
def test_auth_config_never_exposes_server_keys(public_key):
    with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co",
                                "SUPABASE_ANON_KEY": public_key,
                                "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_server"}):
        config = app.get_auth_config()
    assert config["supabase_anon_key"] == ""
    assert config["supabase_enabled"] is False


def test_legacy_founder_password_is_disabled(tmp_path):
    app.DB_PATH = str(tmp_path / "legacy.db")
    app.init_db()
    conn = app.get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=1", (app.hash_password("demo1234"),))
    conn.commit()
    conn.close()
    app.init_db()
    with pytest.raises(HTTPException) as exc:
        app.login(app.Login(email="founder@comment-money.local", password="demo1234"))
    assert exc.value.status_code == 401


def test_config_rejects_untrusted_hosts_without_changes(tmp_path):
    app.DB_PATH = str(tmp_path / "config.db")
    app.init_db()
    admin = app.register(app.Register(email="admin@tenant.test", password="password123"))
    with patch("backend.runtime.ADMIN_EMAILS", {"admin@tenant.test"}), patch("backend.runtime.sync_all_to_supabase") as sync:
        with pytest.raises(HTTPException) as exc:
            app.save_supabase_config(app.SupabaseConfigUpdate(
                supabase_url="https://attacker.test/.supabase.co", supabase_anon_key="a" * 30),
                authorization="Bearer " + admin["token"])
        assert exc.value.status_code == 400
        sync.assert_not_called()

@pytest.fixture(autouse=True)
def _isolate_local_unit_tests(monkeypatch, tmp_path):
    """Keep existing unit tests fast and isolated from live .env Supabase credentials unless explicitly patched."""
    monkeypatch.setenv("JOB_EXECUTION_MODE","inline")
    monkeypatch.setenv("APP_ENV","development")
    monkeypatch.setattr(app, "DB_PATH", str(tmp_path / "isolated.db"))
    app.init_db()
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    for key in ("RESEND_API_KEY","SMTP_HOST","SMTP_USER","SMTP_PASSWORD","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID"):
        monkeypatch.setenv(key, "")
    token = app._API_CONTEXT.set({})
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    yield
    app._API_CONTEXT.reset(token)


# 1. URL parsing tests
def test_video_ids_parsing():
    assert app.video_ids("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == ["dQw4w9WgXcQ"]
    assert app.video_ids("https://youtu.be/dQw4w9WgXcQ") == ["dQw4w9WgXcQ"]
    assert app.video_ids("https://www.youtube.com/shorts/dQw4w9WgXcQ") == ["dQw4w9WgXcQ"]
    assert app.video_ids("https://www.youtube.com/embed/dQw4w9WgXcQ") == ["dQw4w9WgXcQ"]
    assert app.video_ids("dQw4w9WgXcQ") == ["dQw4w9WgXcQ"]
    assert app.video_ids("   ") == []

@patch("backend.runtime.yt")
def test_channel_url_parsing(mock_yt):
    mock_yt.side_effect = [
        {"items": [{"id": "UC1234567890123456789012"}]},
        {"items": [{"contentDetails": {"videoId": "vid12345678"}}, {"contentDetails": {"videoId": "vid87654321"}}]}
    ]
    res = app.video_ids("https://www.youtube.com/@AyanaCare")
    assert res == ["vid12345678", "vid87654321"]

# 2. Sieve filter tests
def test_sieve():
    assert app.sieve({"text": "nice video"}) is False
    assert app.sieve({"text": "first"}) is False
    assert app.sieve({"text": "super bro!"}) is False
    assert app.sieve({"text": "🔥 ❤️ 👏 🙌 😀"}) is False
    assert app.sieve({"text": "Is there an alternative to Emoha for elderly parents?"}) is True
    assert app.sieve({"text": "Mummy ke liye medicine reminder chahiye achha"}) is True
    assert app.sieve({"text": "మా తల్లిదండ్రుల కోసం మంచి వాట్సాప్ కేర్ కావాలి"}) is True

# 3. JSON parsing tests
def test_clean_json():
    assert app.clean_json('{"results": []}') == {"results": []}
    wrapped = '```json\n{"results": [{"score": 85}]}\n```'
    assert app.clean_json(wrapped) == {"results": [{"score": 85}]}
    noisy = 'Here is your analysis:\n{"queries": ["senior care india"]}\nHope this helps!'
    assert app.clean_json(noisy) == {"queries": ["senior care india"]}
    with pytest.raises(ValueError):
        app.clean_json("Not a json at all")

# 4. Error handling tests: YouTube quota exceeded
@patch("httpx.get")
def test_youtube_quota_exceeded(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {
        "error": {
            "errors": [{"reason": "quotaExceeded"}],
            "message": "Quota exceeded"
        }
    }
    mock_get.return_value = mock_resp

    with pytest.raises(HTTPException) as exc_info:
        app.yt("search", q="elderly care")
    assert exc_info.value.status_code == 429
    assert "daily quota exceeded" in exc_info.value.detail

# 5. Error handling tests: YouTube invalid key
@patch("httpx.get")
def test_youtube_invalid_key(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "errors": [{"reason": "keyInvalid"}],
            "message": "API key not valid"
        }
    }
    mock_get.return_value = mock_resp

    with pytest.raises(HTTPException) as exc_info:
        app.yt("search", q="elderly care")
    assert exc_info.value.status_code == 401
    assert "Invalid YouTube API key" in exc_info.value.detail

# 6. Deduplication and zero-score storage test
def test_deduplication_and_zero_scoring(tmp_path):
    test_db = str(tmp_path / "test.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('TestCo', 'WhatsApp care', '', '')")
    conn.commit()
    ws = conn.execute("SELECT * FROM workspaces WHERE name='TestCo'").fetchone()

    fake_comments = [
        {"id": "c1", "vid": "v1", "title": "Vid 1", "author": "User A", "text": "This is a great comment asking for alternative app"},
        {"id": "c2", "vid": "v1", "title": "Vid 1", "author": "User B", "text": "Another comment about finding care for my parents in Delhi"},
    ]

    with patch("backend.runtime.comments", return_value=fake_comments), \
         patch("backend.runtime.gem", return_value={"results": [{"i": 0, "score": 85, "reason": "Buyer pain", "reply": "Try TestCo"}]}):
        res = app.run_scan(ws, ["v1"], per_video=10)
        assert res["scanned"] == 2
        assert res["hot_leads"] == 1

    c1 = conn.execute("SELECT score FROM leads WHERE workspace_id=? AND comment_id='c1'", (ws["id"],)).fetchone()
    c2 = conn.execute("SELECT score FROM leads WHERE workspace_id=? AND comment_id='c2'", (ws["id"],)).fetchone()
    assert c1["score"] == 85
    assert c2["score"] == 0

    with patch("backend.runtime.comments", return_value=fake_comments), \
         patch("backend.runtime.gem") as mock_gem:
        res2 = app.run_scan(ws, ["v1"], per_video=10)
        assert res2["scanned"] == 0
        mock_gem.assert_not_called()

    conn.close()

# 7. Job persistence and server restart recovery
def test_job_persistence_and_server_recovery(tmp_path):
    test_db = str(tmp_path / "test_jobs.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    conn.execute("INSERT INTO jobs(workspace_id, type, status, msg) VALUES (1, 'auto', 'running', 'Searching...')")
    conn.commit()
    jid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    job_info = app.get_job(jid, authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert job_info["id"] == jid
    assert job_info["status"] == "running"
    assert job_info["done"] is False

    app.init_db()

    job_after_restart = app.get_job(jid, authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert job_after_restart["status"] == "interrupted"
    assert job_after_restart["done"] is True
    assert "Server restarted" in job_after_restart["error"]
    conn.close()

# 8. Phase 2: Blocklist filtering
def test_blocklist():
    # Author block (with and without @)
    assert app.is_blocked("@SpamBot", "Hello there", "@spambot, giveaway") is True
    assert app.is_blocked("SpamBot", "Hello there", "@spambot, giveaway") is True
    # Phrase block
    assert app.is_blocked("User1", "Join my free giveaway now", "giveaway\nfreepromo") is True
    # Safe user & content
    assert app.is_blocked("LegitUser", "Looking for good care for mom", "@spambot, giveaway") is False

# 9. Phase 2: Score slider & status filtering
def test_score_and_status_filtering(tmp_path):
    test_db = str(tmp_path / "test_filter.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('FilterCo', 'Care', '', '')")
    conn.commit()
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert 3 leads with different scores and statuses
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) VALUES (?, 'l1', 'v1', 'A', 'Lead 1', 90, 'new')", (wid,))
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) VALUES (?, 'l2', 'v1', 'B', 'Lead 2', 70, 'replied')", (wid,))
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) VALUES (?, 'l3', 'v1', 'C', 'Lead 3', 50, 'new')", (wid,))
    conn.commit()
    conn.close()

    # Filter: score >= 60, status=new -> only l1 (90)
    res_new = app.leads(workspace_id=wid, min_score=60, status="new", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert len(res_new) == 1
    assert res_new[0]["comment_id"] == "l1"

    # Filter: score >= 60, status=replied -> only l2 (70)
    res_replied = app.leads(workspace_id=wid, min_score=60, status="replied", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert len(res_replied) == 1
    assert res_replied[0]["comment_id"] == "l2"

    # Filter: score >= 40, status=all -> l1 (90), l2 (70), l3 (50)
    res_all = app.leads(workspace_id=wid, min_score=40, status="all", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert len(res_all) == 3

# 10. Phase 2: CSV Export
def test_csv_export(tmp_path):
    test_db = str(tmp_path / "test_csv.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('ExportCo', 'Care', '', '')")
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, video_title, author, text, score, reason, reply, status, feedback) "
                 "VALUES (?, 'c10', 'v10', 'Best Video', 'Tester', 'Need this product now', 88, 'Pain point', 'Try ExportCo', 'new', 'good')", (wid,))
    conn.commit()
    conn.close()

    resp = app.export_leads(workspace_id=wid, min_score=60, status="new", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert resp.status_code == 200
    assert resp.media_type == "text/csv"
    csv_text = resp.body.decode("utf-8")
    assert "Score,Author,Video Title,Comment,Why (Reason),Draft Reply,Status,Feedback,YouTube Comment Link" in csv_text
    assert "88,Tester,Best Video,Need this product now,Pain point,Try ExportCo,new,good" in csv_text

# 11. Phase 2: Lead Feedback (good / bad)
def test_lead_feedback(tmp_path):
    test_db = str(tmp_path / "test_fb.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('FbCo', 'Care', '', '')")
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score) VALUES (?, 'c1', 'v1', 'A', 'Text', 80)", (wid,))
    lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    # Mark good
    app.set_feedback(lid, app.Feedback(feedback="good"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    leads = app.leads(workspace_id=wid, min_score=60, status="new", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert leads[0]["feedback"] == "good"

    # Mark bad
    app.set_feedback(lid, app.Feedback(feedback="bad"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    leads = app.leads(workspace_id=wid, min_score=60, status="new", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert leads[0]["feedback"] == "bad"


# 12. Phase 3: Quota Tracking
def test_quota_tracking(tmp_path):
    test_db = str(tmp_path / "test_quota.db")
    app.DB_PATH = test_db
    app.init_db()

    conn = app.get_db()
    today_iso = app.datetime.now(app.timezone.utc).isoformat()
    conn.execute("INSERT INTO runs(workspace_id, units_used, new_leads_count, status, created_at) VALUES (1, 850, 5, 'completed', ?)", (today_iso,))
    conn.execute("INSERT INTO runs(workspace_id, units_used, new_leads_count, status, created_at) VALUES (1, 850, 3, 'completed', ?)", (today_iso,))
    conn.commit()
    conn.close()

    used = app.get_today_quota_used()
    assert used == 1700

# 13. Phase 3: Telegram Alert
@patch("httpx.post")
def test_telegram_alert(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "mock_token", "TELEGRAM_CHAT_ID": "123456"}):
        res = app.send_telegram_alert("Test alert message")
        assert res is True
        mock_post.assert_called_once()
        assert "mock_token" in mock_post.call_args[0][0]
        assert mock_post.call_args[1]["json"]["chat_id"] == "123456"

# 14. Phase 3: Email Alert
@patch("smtplib.SMTP")
def test_email_alert(mock_smtp):
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    with patch.dict(os.environ, {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_USER": "test@gmail.com",
        "SMTP_PASSWORD": "password123",
        "ALERT_EMAIL_TO": "founder@example.com"
    }):
        res = app.send_email_alert("founder@example.com", "Test Subject", "Test Body")
        assert res is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@gmail.com", "password123")
        mock_server.sendmail.assert_called_once()

# 15. Phase 3: Automation Status API
def test_automation_status_api(tmp_path):
    test_db = str(tmp_path / "test_status.db")
    app.DB_PATH = test_db
    app.init_db()

    status = app.automation_status(authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert "scheduler_active" in status
    assert status["interval_hours"] == 168
    assert status["quota_budget"] == 9000
    assert "quota_used_today" in status
    assert "alerts" in status

# 16. Phase 4: User Registration & Authentication
def test_user_registration_and_login(tmp_path):
    test_db = str(tmp_path / "test_auth.db")
    app.DB_PATH = test_db
    app.init_db()

    # Register new user
    reg_res = app.register(app.Register(email="alice@startup.in", password="password123"))
    assert "token" in reg_res
    assert reg_res["user"]["email"] == "alice@startup.in"

    # Login with valid password
    login_res = app.login(app.Login(email="alice@startup.in", password="password123"))
    assert "token" in login_res
    assert login_res["user"]["id"] == reg_res["user"]["id"]

    # Login with wrong password fails
    with pytest.raises(HTTPException) as exc_info:
        app.login(app.Login(email="alice@startup.in", password="wrongpassword"))
    assert exc_info.value.status_code == 401

# 17. Phase 4 Acceptance Gate: Multi-Client Data Isolation ("two test accounts cannot see each other's data")
def test_multi_client_data_isolation(tmp_path):
    test_db = str(tmp_path / "test_isolation.db")
    app.DB_PATH = test_db
    app.init_db()

    # Register Account A (Alice) and Account B (Bob)
    alice = app.register(app.Register(email="alice@client1.com", password="passwordA"))
    bob = app.register(app.Register(email="bob@client2.com", password="passwordB"))

    alice_auth = f"Bearer {alice['token']}"
    bob_auth = f"Bearer {bob['token']}"

    # Alice saves a workspace and adds a lead
    alice_ws = app.add_ws(app.WS(name="AliceProduct", pitch="Alice secret pitch"), authorization=alice_auth)
    alice_wid = alice_ws["id"]

    conn = app.get_db()
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) "
                 "VALUES (?, 'alice_c1', 'v1', 'BuyerA', 'I want Alice product', 90, 'new')", (alice_wid,))
    conn.commit()

    # Bob saves a workspace and adds a lead
    bob_ws = app.add_ws(app.WS(name="BobProduct", pitch="Bob secret pitch"), authorization=bob_auth)
    bob_wid = bob_ws["id"]

    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) "
                 "VALUES (?, 'bob_c1', 'v2', 'BuyerB', 'I want Bob product', 85, 'new')", (bob_wid,))
    conn.commit()
    conn.close()

    # 1. Alice lists workspaces -> sees AliceProduct, NEVER sees BobProduct
    alice_workspaces = app.list_ws(authorization=alice_auth)
    alice_names = [w["name"] for w in alice_workspaces]
    assert "AliceProduct" in alice_names
    assert "BobProduct" not in alice_names

    # 2. Bob lists workspaces -> sees BobProduct, NEVER sees AliceProduct
    bob_workspaces = app.list_ws(authorization=bob_auth)
    bob_names = [w["name"] for w in bob_workspaces]
    assert "BobProduct" in bob_names
    assert "AliceProduct" not in bob_names

    # 3. Bob tries to read Alice's leads -> 404 Unauthorized
    with pytest.raises(HTTPException) as exc_info:
        app.leads(workspace_id=alice_wid, min_score=60, status="new", authorization=bob_auth)
    assert exc_info.value.status_code == 404

    # 4. Alice tries to export Bob's leads -> 404 Unauthorized
    with pytest.raises(HTTPException) as exc_info:
        app.export_leads(workspace_id=bob_wid, min_score=60, status="new", authorization=alice_auth)
    assert exc_info.value.status_code == 404

    # 5. Each account can read its own leads properly
    alice_leads = app.leads(workspace_id=alice_wid, min_score=60, status="new", authorization=alice_auth)
    assert len(alice_leads) == 1
    assert alice_leads[0]["comment_id"] == "alice_c1"

# 18. Phase 4: Per-Account Quota Tracking
def test_per_account_quota_isolation(tmp_path):
    test_db = str(tmp_path / "test_account_quota.db")
    app.DB_PATH = test_db
    app.init_db()

    alice = app.register(app.Register(email="alice@quota.com", password="passwordA"))
    bob = app.register(app.Register(email="bob@quota.com", password="passwordB"))

    conn = app.get_db()
    today_iso = app.datetime.now(app.timezone.utc).isoformat()
    # Alice used 1700 units, Bob used 0
    conn.execute("INSERT INTO runs(workspace_id, user_id, units_used, new_leads_count, status, created_at) VALUES (1, ?, 1700, 4, 'completed', ?)",
                 (alice["user"]["id"], today_iso))
    conn.commit()
    conn.close()

    assert app.get_today_quota_used(user_id=alice["user"]["id"]) == 1700
    assert app.get_today_quota_used(user_id=bob["user"]["id"]) == 0



# 13. Reply prompt: product name + feedback examples reach the AI
def test_prompt_includes_name_and_feedback_examples(tmp_path):
    app.DB_PATH = str(tmp_path / "test_prompt.db")
    app.init_db()
    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('Bharat Chitra', 'Telugu AI video maker', '', 'No links.')")
    ws = conn.execute("SELECT * FROM workspaces WHERE name='Bharat Chitra'").fetchone()
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, reason, score, feedback) "
                 "VALUES (?, 'old1', 'v0', 'A', 'cannot upload telugu fonts in capcut', 'font pain', 70, 'bad')", (ws["id"],))
    conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, feedback) "
                 "VALUES (?, 'old2', 'v0', 'B', 'any good ai video tool for telugu reels?', 90, 'good')", (ws["id"],))
    conn.commit()

    fake = [{"id": "n1", "vid": "v1", "title": "T", "author": "X", "text": "looking for telugu ai video tool please help"}]
    with patch("backend.runtime.comments", return_value=fake), \
         patch("backend.runtime.gem", return_value={"results": []}) as mock_gem:
        app.run_scan(ws, ["v1"], per_video=10)
        prompt = mock_gem.call_args[0][0]

    assert 'PRODUCT NAME: Bharat Chitra' in prompt
    assert 'exactly once' in prompt
    assert 'cannot upload telugu fonts in capcut' in prompt       # bad example
    assert 'any good ai video tool for telugu reels?' in prompt   # good example
    assert 'NOT real leads' in prompt
    conn.close()


def test_prompt_without_feedback_has_no_example_block(tmp_path):
    app.DB_PATH = str(tmp_path / "test_prompt2.db")
    app.init_db()
    conn = app.get_db()
    assert app.feedback_examples(conn, 999) == ""
    conn.close()


# 14. Lead source: channel + links are stored and returned
def test_channel_and_links_returned(tmp_path):
    app.DB_PATH = str(tmp_path / "test_src.db")
    app.init_db()
    conn = app.get_db()
    conn.execute("INSERT INTO workspaces(name, pitch, signals, rules) VALUES ('SrcCo', 'Care app for parents', '', '')")
    conn.commit()
    ws = conn.execute("SELECT * FROM workspaces WHERE name='SrcCo'").fetchone()
    fake = [{"id": "c9", "vid": "vid12345678", "title": "Elder care vlog", "channel": "Asha Vlogs", "cid": "UCabc123",
             "author": "@Ravi", "text": "looking for an app to remind my father about medicines daily"}]
    with patch("backend.runtime.comments", return_value=fake), \
         patch("backend.runtime.gem", return_value={"results": [{"i": 0, "score": 88, "reason": "medicine reminder", "reply": "r"}]}):
        app.run_scan(ws, ["vid12345678"], per_video=10)
    conn.close()
    lead = app.leads(workspace_id=ws["id"], min_score=60, status="new", authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))[0]
    assert lead["channel"] == "Asha Vlogs"
    assert lead["channel_url"] == "https://www.youtube.com/channel/UCabc123"
    assert lead["video_url"] == "https://www.youtube.com/watch?v=vid12345678"
    assert "lc=c9" in lead["link"]


# 15. Guided setup: builds pitch + keywords, reads websites safely
def test_onboard_from_one_line():
    ai = {"pitch": "Ayana helps families care for elderly parents.", "keywords": ["medicine reminder app", " ", "daily check in for dad"],
          "competitors": ["CareZone"], "question": "Which cities?"}
    with patch("backend.runtime.gem", return_value=ai) as g:
        out = app.onboard_suggest(app.Onboard(name="Ayana", about="App for caring for elderly parents", audience="Hyderabad"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    assert out["keywords"] == ["medicine reminder app", "daily check in for dad"]
    assert "CareZone" not in out["pitch"] and out["read_website"] is False
    assert out["competitors"] == []  # AI guesses are not seller-confirmed facts.
    assert "Hyderabad" in g.call_args[0][0]

def test_onboard_reads_website_text():
    ai = {"pitch": "p", "keywords": ["k"], "competitors": []}
    with patch("backend.runtime.fetch_site_text", return_value="Medicine reminders and emergency keywords") as f, \
         patch("backend.runtime.gem", return_value=ai) as g:
        out = app.onboard_suggest(app.Onboard(name="Ayana", about="https://ayana.example.in"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    f.assert_called_once()
    assert out["read_website"] is True
    assert "emergency keywords" in g.call_args[0][0]

def test_onboard_needs_something_to_work_with():
    import pytest
    with pytest.raises(app.HTTPException):
        app.onboard_suggest(app.Onboard(name="Ayana", about="hi"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))
    with pytest.raises(app.HTTPException):
        app.onboard_suggest(app.Onboard(name="", about="a real description here"), authorization="Bearer " + app.create_access_token(1, "founder@comment-money.local"))

def test_website_fetch_refuses_internal_addresses():
    import pytest
    for bad in ["http://127.0.0.1:8000/api/leads", "http://localhost/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/"]:
        with pytest.raises(app.HTTPException):
            app.fetch_site_text(bad)


# ---------- Step 3: plans, limits, quota protection ----------
def _user(tmp_path, name, plan=None):
    app.DB_PATH = str(tmp_path / f"{name}.db")
    app.init_db()
    u = app.register(app.Register(email=f"{name}@x.com", password="secret12"))
    auth = f"Bearer {u['token']}"
    wid = app.add_ws(app.WS(name="P", pitch="A real product pitch here"), authorization=auth)["id"]
    if plan:
        conn = app.get_db(); conn.execute("UPDATE users SET plan=?,billing_start=?,billing_end=? WHERE id=?", (plan,app.commerce.iso(app.commerce.now()),app.commerce.iso(app.commerce.next_month(app.commerce.now())),u["user"]["id"])); conn.commit(); conn.close()
    return u["user"]["id"], auth, wid

def _set_jobs(status):
    conn = app.get_db(); conn.execute("UPDATE jobs SET status=?", (status,)); conn.commit(); conn.close()

def test_free_plan_allows_two_searches_only(tmp_path):
    uid, auth, wid = _user(tmp_path, "free1")
    with patch("backend.runtime.run_auto_job"):
        app.auto(app.Auto(workspace_id=wid), authorization=auth)
        with pytest.raises(app.HTTPException) as e:                      # one already running
            app.auto(app.Auto(workspace_id=wid), authorization=auth)
        assert e.value.status_code == 409
        _set_jobs("done")
        app.auto(app.Auto(workspace_id=wid), authorization=auth)
        _set_jobs("done")
        with pytest.raises(app.HTTPException) as e:                      # third search
            app.auto(app.Auto(workspace_id=wid), authorization=auth)
        assert e.value.status_code == 403
        assert app.plan_status(authorization=auth)["can_search"] is False
        _set_jobs("error")                                               # our errors are never charged to the user
        assert app.plan_status(authorization=auth)["searches_used"] == 0
        app.auto(app.Auto(workspace_id=wid), authorization=auth)

def test_free_search_is_cheaper_and_capped(tmp_path):
    uid, auth, wid = _user(tmp_path, "free2")
    with patch("backend.runtime.run_auto_job") as job:
        app.auto(app.Auto(workspace_id=wid, max_videos=50), authorization=auth)
    time.sleep(0.2)
    args = job.call_args[0]
    assert args[3] == 2 and args[-1] == 1          # trial has a deliberately smaller discovery budget
    conn = app.get_db()
    assert conn.execute("SELECT units_used FROM runs WHERE user_id=?", (uid,)).fetchone()[0] == 50
    conn.close()

def test_global_budget_blocks_without_using_a_search(tmp_path):
    uid, auth, wid = _user(tmp_path, "cap1")
    with patch("backend.runtime.DAILY_QUOTA_BUDGET", 49), patch("backend.runtime.run_auto_job"):
        with pytest.raises(app.HTTPException) as e:
            app.auto(app.Auto(workspace_id=wid), authorization=auth)
    assert e.value.status_code == 429
    conn = app.get_db()
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()

def test_free_users_cannot_eat_the_whole_budget(tmp_path):
    uid, auth, wid = _user(tmp_path, "cap2")
    conn = app.get_db()
    conn.execute("INSERT INTO runs(workspace_id,user_id,units_used,status,created_at) VALUES (1,?,5380,'completed',?)", (uid, app.datetime.now(app.timezone.utc).isoformat()))
    conn.commit(); conn.close()
    with patch("backend.runtime.run_auto_job"):
        with pytest.raises(app.HTTPException) as e:                      # 5380 + 50 > 60% of 9000
            app.auto(app.Auto(workspace_id=wid), authorization=auth)
        assert e.value.status_code == 429
        jid, _ = app.reserve_search(1, wid, "auto", 850)                 # the unlimited founder account still has room
        assert jid

def test_quota_day_follows_pacific_midnight(tmp_path):
    app.DB_PATH = str(tmp_path / "pt.db"); app.init_db()
    start = app.datetime.fromisoformat(app.quota_day_start_utc())
    before = (start - app.timedelta(minutes=1)).isoformat()
    after = (start + app.timedelta(minutes=1)).isoformat()
    conn = app.get_db()
    conn.execute("INSERT INTO runs(workspace_id,user_id,units_used,status,created_at) VALUES (1,1,500,'completed',?)", (before,))
    conn.execute("INSERT INTO runs(workspace_id,user_id,units_used,status,created_at) VALUES (1,1,700,'completed',?)", (after,))
    conn.commit(); conn.close()
    assert app.get_today_quota_used() == 700

def _add_leads(wid, n, base=90):
    conn = app.get_db()
    for i in range(n):
        conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) VALUES (?,?,?,?,?,?, 'new')",
                     (wid, f"c{i}", "v1", f"@buyer{i}", f"secret comment number {i}", base - i))
    conn.commit(); conn.close()

def test_free_plan_locks_leads_on_the_server(tmp_path):
    uid, auth, wid = _user(tmp_path, "lock1")
    _add_leads(wid, 33, base=99)
    res = app.leads(workspace_id=wid, min_score=60, status="new", authorization=auth)
    open_, locked = [r for r in res if not r["locked"]], [r for r in res if r["locked"]]
    assert len(open_) == 30 and len(locked) == 3
    assert [r["score"] for r in open_] == sorted([r["score"] for r in open_], reverse=True)
    assert min(r["score"] for r in open_) > max(r["score"] for r in locked) - 1      # best 10 are the unlocked ones
    assert res[-3:] == locked                                            # locked leads come last
    assert "secret comment" not in json.dumps(locked) and "text" not in locked[0]
    # stable: a new better lead does not take over an unlocked slot
    _add_leads_conn = app.get_db()
    _add_leads_conn.execute("INSERT INTO leads(workspace_id, comment_id, video_id, author, text, score, status) VALUES (?, 'newbest','v1','@x','newest',99,'new')", (wid,))
    _add_leads_conn.commit(); _add_leads_conn.close()
    again = app.leads(workspace_id=wid, min_score=60, status="new", authorization=auth)
    assert sum(1 for r in again if not r["locked"]) == 30
    assert any(r["locked"] and r["score"] == 99 for r in again)
    # CSV only contains unlocked leads
    csv_text = app.export_leads(workspace_id=wid, min_score=60, status="new", authorization=auth).body.decode()
    assert "newest" not in csv_text and csv_text.count("secret comment") == 30
    # plan status numbers
    st = app.plan_status(authorization=auth)
    assert st["leads_unlocked"] == 30 and st["locked_total"] == 4 and st["locked_strong"] == 1

def test_unlimited_plan_sees_everything(tmp_path):
    uid, auth, wid = _user(tmp_path, "lock2", plan="unlimited")
    _add_leads(wid, 13)
    res = app.leads(workspace_id=wid, min_score=60, status="new", authorization=auth)
    assert len(res) == 13 and not any(r["locked"] for r in res)

def test_alerts_never_include_locked_leads(tmp_path):
    uid, auth, wid = _user(tmp_path, "lock3")
    _add_leads(wid, 32, base=99)
    conn = app.get_db()
    app.unlock_top_leads(conn, uid, wid)
    new = [{"id": f"c{i}", "text": f"t{i}"} for i in range(32)]
    shown, hidden = app.alertable(conn, uid, wid, new)
    conn.close()
    assert len(shown) == 30 and hidden == 2

def test_failed_job_before_searching_costs_no_quota(tmp_path):
    uid, auth, wid = _user(tmp_path, "fail1")
    jid, run_id = app.reserve_search(uid, wid, "auto", 450)
    with patch("backend.runtime.gem", side_effect=app.HTTPException(401, "bad key")):
        app.run_auto_job(jid, wid, 80, 8, run_id=run_id, n_queries=4)
    conn = app.get_db()
    run = conn.execute("SELECT units_used, status FROM runs WHERE id=?", (run_id,)).fetchone()
    job = conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    assert (run["units_used"], run["status"], job["status"]) == (0, "failed", "error")

def test_scheduler_skips_free_users(tmp_path):
    uid, auth, wid = _user(tmp_path, "sched1")
    with patch("backend.runtime.run_auto_job") as job:
        app.scheduled_auto_run_all()
        job.assert_not_called()
        conn = app.get_db(); conn.execute("UPDATE users SET plan='unlimited' WHERE id=?", (uid,)); conn.commit(); conn.close()
        app.scheduled_auto_run_all()
        job.assert_called_once()

def test_admin_can_change_plans_and_guests_cannot(tmp_path):
    app.DB_PATH = str(tmp_path / "adm.db"); app.init_db()
    boss = app.register(app.Register(email="boss@x.com", password="secret12"))
    other = app.register(app.Register(email="other@x.com", password="secret12"))
    with patch("backend.runtime.ADMIN_EMAILS", {"boss@x.com"}):
        app.admin_set_plan(app.PlanChange(email="other@x.com", plan="unlimited"), authorization=f"Bearer {boss['token']}")
        assert app.plan_of(other["user"]["id"])["key"] == "unlimited"
        with pytest.raises(app.HTTPException) as e:
            app.admin_set_plan(app.PlanChange(email="boss@x.com", plan="unlimited"), authorization=f"Bearer {other['token']}")
        assert e.value.status_code == 403
        with pytest.raises(app.HTTPException) as e:
            app.admin_set_plan(app.PlanChange(email="other@x.com", plan="free"), authorization=None)
        assert e.value.status_code == 401

def test_upgrade_interest_is_recorded(tmp_path):
    uid, auth, wid = _user(tmp_path, "int1")
    app.upgrade_interest(app.Interest(plan="paid"), authorization=auth)
    conn = app.get_db()
    assert conn.execute("SELECT COUNT(*) FROM upgrade_interest WHERE user_id=?", (uid,)).fetchone()[0] == 1
    conn.close()


# ---------- Supabase: Data Storing + Auth (Sign Up / Login) + Emails ----------
def test_supabase_auth_signup_login_and_magic_link(tmp_path):
    app.DB_PATH = str(tmp_path / "sb_auth.db")
    app.init_db()
    env = {
        "SUPABASE_URL": "https://comment-lead.supabase.co",
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_anon_key_123456"
    }
    with patch.dict(os.environ, env):
        with patch("httpx.post") as mock_post, patch("httpx.request") as mock_req:
            # 1. Sign Up via Supabase Auth + sync user & workspace + welcome email log
            signup_resp = MagicMock()
            signup_resp.status_code = 200
            signup_resp.content = b'{"ok":true}'
            signup_resp.json.return_value = {
                "access_token": "sb_jwt_token_123",
                "user": {
                    "id": "11111111-2222-3333-4444-555555555555",
                    "email": "guna@commentlead.in",
                    "user_metadata": {"full_name": "Guna Kanumuri"}
                }
            }
            mock_post.return_value = signup_resp
            mock_req_resp = MagicMock(status_code=201, content=b"[]")
            mock_req_resp.json.return_value = []
            mock_req.return_value = mock_req_resp

            reg = app.register(app.Register(email="guna@commentlead.in", password="password123", name="Guna Kanumuri"))
            assert reg["auth_provider"] == "supabase"
            assert reg["supabase_access_token"] == "sb_jwt_token_123"
            assert reg["user"]["email"] == "guna@commentlead.in"
            assert reg["user"]["supabase_uid"] == "11111111-2222-3333-4444-555555555555"

            # 2. Magic Link Email via Supabase Auth (/auth/v1/otp)
            otp_resp = MagicMock(status_code=200, content=b"{}")
            otp_resp.json.return_value = {}
            mock_post.return_value = otp_resp
            ml = app.send_magic_link_email(app.EmailAction(email="guna@commentlead.in"))
            assert ml["ok"] is True
            assert "Magic login link sent" in ml["msg"]

            # 3. Password Reset Email via Supabase Auth (/auth/v1/recover)
            pw = app.send_password_reset_email(app.EmailAction(email="guna@commentlead.in"))
            assert pw["ok"] is True

            # Verify emails were logged in email_logs
            emails = app.list_supabase_emails(authorization="Bearer " + reg["token"])
            assert len(emails) >= 3
            assert any(e["email_type"] == "magic_link" for e in emails)
            assert any(e["email_type"] == "password_reset" for e in emails)


def test_supabase_data_storing_and_email_outbox(tmp_path):
    app.DB_PATH = str(tmp_path / "sb_data.db")
    app.init_db()
    env = {
        "SUPABASE_URL": "https://comment-lead.supabase.co",
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_anon_key_123456",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
        "SMTP_HOST": "",
        "SMTP_USER": "",
        "SMTP_PASSWORD": ""
    }
    with patch.dict(os.environ, env):
        with patch("httpx.request") as mock_req, patch("httpx.post") as mock_post:
            mock_req_resp = MagicMock(status_code=200, content=b"[]")
            mock_req_resp.json.return_value = []
            mock_req.return_value = mock_req_resp

            edge_resp = MagicMock(status_code=200, content=b'{"ok":true}')
            edge_resp.json.return_value = {"ok": True}
            mock_post.return_value = edge_resp

            # Send lead alert email through Supabase Edge Function + Outbox
            sent = app.send_email_alert("founder@commentlead.in", "3 New Leads", "Lead details here")
            assert sent is True

            # Trigger full 2-way Supabase database sync
            sync_res = app.sync_all_to_supabase()
            assert sync_res["ok"] is True
            assert sync_res["pushed"]["users"] >= 1
            assert sync_res["pushed"]["emails"] >= 1

            # Verify SQL schema endpoint returns RLS + tables
            schema = app.get_supabase_schema()
            assert "enable row level security" in schema["sql"].lower()
            assert "create table if not exists leads" in schema["sql"].lower()
            assert "app_private" in schema["sql"]

def test_production_health_and_lead_ownership():
    h = app.health_check()
    assert h["status"] == "ok"
    assert h["db"] == "connected"
    assert "scheduler" in h

    # Verify another user cannot modify a lead owned by someone else
    u1 = app.register(app.Register(email="owner@example.com", password="password123", name="Owner"))
    u2 = app.register(app.Register(email="intruder@example.com", password="password123", name="Intruder"))
    conn = app.get_db()
    ws1 = conn.execute("SELECT id FROM workspaces WHERE user_id=?", (u1["user"]["id"],)).fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO leads(workspace_id, comment_id, video_id, video_title, author, text, score, status) VALUES (?,?,?,?,?,?,?,?)",
        (ws1, "c_own_1", "v1", "Title", "@buyer", "Need this", 90, "new")
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()

    with pytest.raises(app.HTTPException) as exc:
        app.set_status(lid, app.Status(status="replied"), authorization=f"Bearer {u2['token']}")
    assert exc.value.status_code == 403

    app.leads(ws1, authorization=f"Bearer {u1['token']}")  # Unlock the owner's eligible lead.
    res = app.set_status(lid, app.Status(status="replied"), authorization=f"Bearer {u1['token']}")
    assert res["ok"] is True




# Pilot regressions: real evidence, re-analysis, outcomes and bounded API usage.
def _pilot_workspace(profile=None):
    auth = "Bearer " + app.create_access_token(1, "founder@comment-money.local")
    wid = app.add_ws(app.WS(name="PilotApp",pitch="Find customer conversations with lead scoring",profile=profile),authorization=auth)["id"]
    conn = app.get_db()
    ws = conn.execute("SELECT * FROM workspaces WHERE id=?",(wid,)).fetchone()
    conn.close()
    return auth,ws


def _pilot_comment(**values):
    return {"id":"c-pilot","vid":"abcdefghijk","title":"Customer discovery tools","author":"@buyer",
            "text":"Need a cheaper tool with lead scoring", "published_at":"2026-10-25T10:00:00Z", **values}


def test_preview_never_fabricates_on_api_failure():
    with patch("backend.runtime.video_ids",return_value=["abcdefghijk"]), patch("backend.runtime.comments",side_effect=HTTPException(429,"Quota reached")):
        with pytest.raises(HTTPException) as exc:
            app.free_preview(app.FreePreview(product={"description":"A tool that offers lead scoring for small software founders.","customer":"Small software founders"},query="test"))
    assert exc.value.status_code==429


def test_preview_empty_and_real_source_metadata():
    with patch("backend.runtime.video_ids",return_value=[]),patch("backend.runtime.yt",return_value={"items":[]}):
        result=app.free_preview(app.FreePreview(product={"description":"A tool that offers lead scoring for small software founders.","customer":"Small software founders"},query="no results"))
    assert result["leads"]==[] and result["video"] is None and result["qualified"] is False
    with patch("backend.runtime.video_ids",return_value=["abcdefghijk"]),patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"buyer_type":"buyer","direct_match":True,"intent":"recommendation","need":"Needs lead scoring","quote":"lead scoring","feature":"lead scoring","reason":"The product offers the requested feature."}]}):
        result=app.free_preview(app.FreePreview(product={"description":"A tool that offers lead scoring for small software founders.","customer":"Small software founders"},query="test"))
    assert result["leads"][0]["text"]==_pilot_comment()["text"]
    assert result["leads"][0]["published_at"]==_pilot_comment()["published_at"]
    assert result["leads"][0]["reply"]=="" and result["qualified"] is False
    assert "1.2M" not in json.dumps(result)
    assert "lc=c-pilot" in result["leads"][0]["link"]


@pytest.mark.parametrize("text",["Price?","Hyderabad delivery?","కావాలి","कीमत?","Need alternative","How much?"])
def test_short_buyer_requests_are_preserved(text):
    assert app.sieve({"text":text})


def test_comments_preserve_top_level_source_id_and_dates():
    comment={"id":"thread-id","snippet":{"topLevelComment":{"id":"actual-comment-id","snippet":{
        "textDisplay":"Price?","authorDisplayName":"Buyer","publishedAt":"2026-10-25T10:00:00Z","updatedAt":"2026-10-26T11:00:00Z"}}}}
    with patch("backend.runtime.yt",side_effect=[{"items":[{"snippet":{"title":"Video"}}]},{"items":[comment]}]):
        rows=app.comments("abcdefghijk",10)
    assert rows[0]["id"]=="actual-comment-id"
    assert rows[0]["published_at"]=="2026-10-25T10:00:00+00:00"
    assert rows[0]["source_updated_at"]=="2026-10-26T11:00:00+00:00"


def test_recent_comments_prioritized_and_evidence_is_source_backed():
    auth,ws=_pilot_workspace()
    old=_pilot_comment(id="old",published_at="2025-01-01T00:00:00Z")
    fresh=_pilot_comment(id="fresh")
    with patch("backend.runtime.comments",return_value=[old,fresh]),patch("backend.runtime.gem",return_value={"results":[{
        "i":0,"score":90,"buyer_type":"buyer","need":"Cheaper tool","feature":"lead scoring","quote":"Need a cheaper tool",
        "reason":"Needs lead scoring", "reply":"PilotApp offers lead scoring. What is your budget?","unknowns":[]} ]}) as gem:
        app.run_scan(ws,["abcdefghijk"],20)
    assert gem.call_args.args[0].index("2026-10-25") < gem.call_args.args[0].index("2025-01-01")
    lead=app.leads(ws["id"],authorization=auth)[0]
    assert lead["comment_id"]=="fresh"
    assert lead["evidence"]["quote"] in lead["text"]
    assert "Budget unverified" in lead["evidence"]["unknowns"]
    assert lead["analysis_stale"] is False


@pytest.mark.parametrize("category",["seller","student","tutorial","generic"])
def test_nonbuyers_cannot_receive_high_scores(category):
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":99,"buyer_type":category}]}):
        result=app.run_scan(ws,["abcdefghijk"],10)
    assert result["hot_leads"]==0
    assert app.leads(ws["id"],min_score=40,authorization=auth)==[]


def test_hallucinated_evidence_is_rejected():
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":99,"quote":"I want to buy right now"}]}):
        app.run_scan(ws,["abcdefghijk"],10)
    assert app.leads(ws["id"],min_score=40,authorization=auth)==[]


def test_failed_analysis_can_be_retried():
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",side_effect=HTTPException(503,"AI unavailable")):
        with pytest.raises(HTTPException):app.run_scan(ws,["abcdefghijk"],10)
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":85}]}):
        result=app.run_scan(ws,["abcdefghijk"],10)
    assert result["scanned"]==1 and result["hot_leads"]==1


def test_profile_change_marks_scores_stale_and_reassessment_preserves_history():
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":85}]}):
        app.run_scan(ws,["abcdefghijk"],10)
    lead=app.leads(ws["id"],authorization=auth)[0]
    app.set_outcome(lead["id"],app.Outcome(stage="purchased",revenue="19.99",currency="USD"),authorization=auth)
    app.add_ws(app.WS(name="PilotApp",pitch="Now offers lead scoring and regional customer discovery"),authorization=auth)
    assert app.leads(ws["id"],status="all",authorization=auth)[0]["analysis_stale"] is True
    jid,run_id=app.reserve_search(1,ws["id"],"reassess",0)
    with patch("backend.runtime.yt") as yt,patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":80}]}):
        app.run_reassessment(jid,ws["id"],run_id)
        yt.assert_not_called()
    lead2=app.leads(ws["id"],status="all",authorization=auth)[0]
    assert lead2["id"]==lead["id"] and not lead2["analysis_stale"]
    assert lead2["outcome"]=="purchased" and lead2["revenue_minor"]==1999


def test_outcomes_are_audited_idempotent_and_keep_currencies_separate():
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment(id="usd"),_pilot_comment(id="inr")]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":85},{"i":1,"score":90}]}):
        app.run_scan(ws,["abcdefghijk"],10)
    rows=app.leads(ws["id"],authorization=auth)
    for lead,currency,amount in zip(rows,["USD","INR"],["12.34","999.00"]):
        body=app.Outcome(stage="purchased",revenue=amount,currency=currency)
        app.set_outcome(lead["id"],body,authorization=auth)
        app.set_outcome(lead["id"],body,authorization=auth)
    metrics=app.workspace_metrics(ws["id"],authorization=auth)
    assert metrics["api_cost_per_useful_lead_usd"] is None  # No tracked usage is unknown, not a free acquisition.
    assert metrics["funnel"]["purchased"]==2
    assert metrics["revenue_minor_by_currency"]=={"USD":1234,"INR":99900}
    conn=app.get_db();assert conn.execute("SELECT COUNT(*) FROM lead_outcome_events").fetchone()[0]==2;conn.close()
    with pytest.raises(HTTPException): app.set_outcome(rows[0]["id"],app.Outcome(stage="irrelevant"),authorization=auth)
    with pytest.raises(HTTPException): app.set_outcome(rows[0]["id"],app.Outcome(stage="contacted",revenue=1),authorization=auth)
    with pytest.raises(ValidationError):app.Outcome(stage="purchased",revenue="1.999")


def test_youtube_retry_ledger_and_separate_search_bucket():
    transient=MagicMock(status_code=503);transient.json.return_value={}
    success=MagicMock(status_code=200);success.json.return_value={"items":[]}
    with patch("httpx.get",side_effect=[transient,success]),patch("backend.runtime.time.sleep"):
        app.yt("search",q="customer discovery")
    conn=app.get_db()
    assert conn.execute("SELECT SUM(units) FROM api_usage WHERE bucket='youtube_search'").fetchone()[0]==2
    assert conn.execute("SELECT COUNT(*) FROM api_usage WHERE bucket='youtube_other'").fetchone()[0]==0
    conn.close()
    with patch("backend.runtime.DAILY_SEARCH_BUDGET",2),patch("httpx.get") as get:
        with pytest.raises(HTTPException) as exc:app.yt("search",q="another")
        assert exc.value.status_code==429
        get.assert_not_called()


def test_usage_cost_remains_unknown_without_prices_and_counts_thinking_tokens():
    metadata={"promptTokenCount":100,"candidatesTokenCount":20,"thoughtsTokenCount":30,"totalTokenCount":150}
    uid=app.begin_api_call("gemini","model")
    app.complete_api_call(uid,"200",metadata,"model")
    conn=app.get_db();assert conn.execute("SELECT cost_usd FROM api_usage WHERE id=?",(uid,)).fetchone()[0] is None;conn.close()
    with patch.dict(os.environ,{"GEMINI_PRICING_JSON":json.dumps({"model":{"input_usd_per_million":1,"output_usd_per_million":2}})}):
        app.complete_api_call(uid,"200",metadata,"model")
    conn=app.get_db();row=conn.execute("SELECT * FROM api_usage WHERE id=?",(uid,)).fetchone();conn.close()
    assert row["output_tokens"]==50 and row["cost_usd"]==pytest.approx(.0002)


def test_pilot_feedback_requires_ownership():
    auth,ws=_pilot_workspace()
    app.save_pilot_feedback(ws["id"],app.PilotFeedback(would_pay="yes",notes="Useful conversations"),authorization=auth)
    assert app.workspace_metrics(ws["id"],authorization=auth)["pilot_feedback"]["would_pay"]=="yes"
    other=app.register(app.Register(email="other@pilot.test",password="password123"))
    with pytest.raises(HTTPException):app.workspace_metrics(ws["id"],authorization="Bearer "+other["token"])
    with pytest.raises(HTTPException):app.save_pilot_feedback(ws["id"],app.PilotFeedback(would_pay="no"),authorization="Bearer "+other["token"])


@pytest.mark.parametrize("method,path,body",[
    ("get","/api/workspaces/1/metrics",None),
    ("post","/api/workspaces/1/reassess",{}),
    ("post","/api/workspaces/1/pilot-feedback",{"would_pay":"yes"}),
    ("post","/api/leads/1/outcome",{"stage":"contacted"}),
    ("get","/api/admin/operations",None),
    ("get","/api/admin/pilot",None),
])
def test_pilot_http_routes_require_login(method,path,body):
    from fastapi.testclient import TestClient
    response=TestClient(app.app).request(method,path,json=body)
    assert response.status_code==401


def test_usage_budget_is_atomic_under_concurrent_requests():
    from concurrent.futures import ThreadPoolExecutor
    def reserve(_):
        try:return app.begin_api_call("youtube","search")
        except HTTPException:return None
    with patch("backend.runtime.DAILY_SEARCH_BUDGET",2),ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(reserve,range(3)))
    assert sum(value is not None for value in results)==2
    conn=app.get_db();assert conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]==2;conn.close()


def test_model_cannot_invent_supported_product_features():
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{
        "i":0,"score":99,"buyer_type":"buyer","feature":"Instagram DM automation","quote":"Need a cheaper tool"}]}):
        result=app.run_scan(ws,["abcdefghijk"],10)
    assert result["hot_leads"]==0
    assert app.leads(ws["id"],min_score=40,authorization=auth)==[]


def test_outcome_http_ownership_and_purchase_round_trip():
    from fastapi.testclient import TestClient
    auth,ws=_pilot_workspace()
    with patch("backend.runtime.comments",return_value=[_pilot_comment()]),patch("backend.runtime.gem",return_value={"results":[{"i":0,"score":85}]}):
        app.run_scan(ws,["abcdefghijk"],10)
    lead=app.leads(ws["id"],authorization=auth)[0]
    other=app.register(app.Register(email="http-other@pilot.test",password="password123"))
    client=TestClient(app.app)
    response=client.post(f"/api/leads/{lead['id']}/outcome",json={"stage":"purchased","revenue":"9.99","currency":"USD"},headers={"Authorization":"Bearer "+other["token"]})
    assert response.status_code==403
    response=client.post(f"/api/leads/{lead['id']}/outcome",json={"stage":"purchased","revenue":"9.99","currency":"USD"},headers={"Authorization":auth})
    assert response.status_code==200 and response.json()["revenue_minor"]==999
    response=client.get(f"/api/workspaces/{ws['id']}/metrics",headers={"Authorization":auth})
    assert response.json()["revenue_minor_by_currency"]=={"USD":999}


def test_pilot_counts_only_feedback_participants_and_never_double_counts_user():
    user=app.register(app.Register(email="pilot-participant@pilot.test",password="password123"))
    conn=app.get_db()
    conn.execute("UPDATE users SET plan='unlimited' WHERE id=?",(user['user']['id'],));conn.commit();conn.close()
    auth="Bearer "+user["token"]
    profile=_matching_profile(business_type="Software startup",delivery_scope="global",locations="Worldwide")
    first=app.add_ws(app.WS(name="Pilot first",pitch="Find customer conversations",profile=profile),authorization=auth)["id"]
    second=app.add_ws(app.WS(name="Pilot second",pitch="Find customer conversations",profile=profile),authorization=auth)["id"]
    with patch("backend.runtime.ADMIN_EMAILS",{"pilot-participant@pilot.test"}):
        assert app.pilot_overview(authorization=auth)["founders"]["participants"]==0
        for wid in (first,second):app.save_pilot_feedback(wid,app.PilotFeedback(would_pay="yes"),authorization=auth)
        cohort=app.pilot_overview(authorization=auth)["founders"]
    assert cohort["participants"]==1 and cohort["would_pay"]==1



def test_unconfirmed_supabase_signup_never_issues_local_session():
    response=MagicMock(status_code=200,content=b'{}')
    response.json.return_value={"id":"11111111-2222-3333-4444-555555555555","email":"pending@pilot.test","identities":[]}
    with patch.dict(os.environ,{"SUPABASE_URL":"https://test.supabase.co","SUPABASE_ANON_KEY":"public-key"}),patch("httpx.post",return_value=response):
        result=app.register(app.Register(email="pending@pilot.test",password="password123"))
    assert result["confirmation_required"] is True and not result.get("token")
    conn=app.get_db();assert conn.execute("SELECT COUNT(*) FROM users WHERE email='pending@pilot.test'").fetchone()[0]==0;conn.close()


def test_unconfirmed_supabase_login_cannot_fall_back_to_local_password():
    app.register(app.Register(email="pending-login@pilot.test",password="password123"))
    response=MagicMock(status_code=400,content=b'{}')
    response.json.return_value={"error_description":"Email not confirmed"}
    with patch.dict(os.environ,{"SUPABASE_URL":"https://test.supabase.co","SUPABASE_ANON_KEY":"public-key"}),patch("httpx.post",return_value=response):
        with pytest.raises(HTTPException) as exc:
            app.login(app.Login(email="pending-login@pilot.test",password="password123"))
    assert exc.value.status_code==401


def test_public_local_signup_cannot_claim_an_administrator_address():
    with patch("backend.runtime.ADMIN_EMAILS",{"administrator@pilot.test"}):
        with pytest.raises(HTTPException) as exc:
            app.register(app.Register(email="administrator@pilot.test",password="password123"))
    assert exc.value.status_code==403

def test_preview_topic_mode_never_interprets_topic_as_video_id():
    with patch.object(app,'video_ids') as ids,patch.object(app,'yt',return_value={'items':[]}) as search:
        result=app.free_preview(app.FreePreview(product={"description":"A tool that offers lead scoring for small software founders.","customer":"Small software founders"},query='photography',mode='topic'))
    ids.assert_not_called()
    assert search.call_args.kwargs['q']=='photography'
    assert result['leads']==[]

def test_preview_video_mode_does_not_fall_back_to_keyword_search():
    with patch.object(app,'video_ids',return_value=[]),patch.object(app,'yt') as search:
        with pytest.raises(HTTPException) as exc:
            app.free_preview(app.FreePreview(product={"description":"A tool that offers lead scoring for small software founders.","customer":"Small software founders"},query='not a video',mode='video'))
    assert exc.value.status_code==400
    search.assert_not_called()
