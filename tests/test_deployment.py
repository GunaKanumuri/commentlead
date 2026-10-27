"""Deployment contracts for manifest installation and fail-closed API startup."""
from pathlib import Path
import tomllib
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import runtime
from backend.system import http_startup


def test_vercel_manifest_declares_all_direct_runtime_dependencies():
    config=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf8'))
    names={item.split('==')[0].lower() for item in config['project']['dependencies']}
    assert {'fastapi','uvicorn','httpx','python-dotenv','apscheduler','pyjwt','pydantic','tzdata','psycopg[binary]'}<=names
    assert config['tool']['vercel']['entrypoint']=='backend.main:app'
    assert config['tool']['uv']['package'] is False
    assert 'pytest' not in names


def test_setup_failure_keeps_public_assets_available_and_blocks_private_api(monkeypatch):
    monkeypatch.setattr(runtime.app.state,'startup_error',None,raising=False)
    monkeypatch.setattr(runtime,'_COMMERCIAL_READY',False,raising=False)
    with patch.object(runtime,'commercial_startup',side_effect=RuntimeError('Private configuration detail')):
        http_startup()
    client=TestClient(runtime.app)
    with patch.object(runtime,'get_db',side_effect=AssertionError('Private storage must not be accessed')):
        assert client.get('/').status_code==200
        assert client.get('/assets/styles.css').status_code==200
        assert client.get('/assets/app.js').status_code==200
        assert client.get('/api/auth/config').status_code==200
        assert client.get('/api/pricing').status_code==200
        response=client.get('/api/workspaces')
        assert response.status_code==503
        assert 'Private configuration detail' not in response.text
        assert client.post('/api/scan',json={'workspace_id':1,'urls':[]}).status_code==503
        assert client.get('/api/health').status_code==503


def test_successful_startup_clears_setup_gate(monkeypatch):
    monkeypatch.setattr(runtime.app.state,'startup_error','setup_required',raising=False)
    monkeypatch.setattr(runtime,'_COMMERCIAL_READY',False,raising=False)
    with patch.object(runtime.commerce,'production_preflight'),patch.object(runtime.database,'verify_schema'):
        runtime.commercial_startup()
    assert runtime.app.state.startup_error is None
    assert runtime._COMMERCIAL_READY is True
