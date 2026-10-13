import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as a


@pytest.fixture
def linux_cli(monkeypatch):
    monkeypatch.setattr(a.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(a, 'CLAUDE_EXE', 'claude')
    monkeypatch.delenv('CLAUDE_OAUTH_EXPIRES_AT', raising=False)
    monkeypatch.delenv('CLAUDE_CODE_OAUTH_TOKEN', raising=False)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'must-not-be-used')


def test_api_key_does_not_enable_subscription(linux_cli):
    runtime = asyncio.run(a.runtime_status())
    assert runtime['claude_cli_installed'] is True
    assert runtime['claude_available'] is False
    client = TestClient(a.app)
    for endpoint in ('/api/generate-claude', '/api/generate-both'):
        response = client.post(endpoint, json={'sector': 'QA'})
        assert response.status_code == 503
        assert response.json()['detail'] == runtime['claude_unavailable_reason']


def test_oauth_enables_subscription(linux_cli, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'subscription')
    assert asyncio.run(a.runtime_status())['claude_available'] is True


def test_expired_oauth_is_disabled(linux_cli, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'subscription')
    monkeypatch.setenv('CLAUDE_OAUTH_EXPIRES_AT', '1')
    assert asyncio.run(a.runtime_status())['claude_available'] is False
    assert TestClient(a.app).post('/api/generate-claude', json={'sector': 'QA'}).status_code == 503


def test_cli_environment_excludes_api_billing(linux_cli, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'subscription')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'api-auth')
    run = MagicMock(return_value=MagicMock(returncode=0, stdout=b'{"result":"READY","is_error":false}', stderr=b''))
    monkeypatch.setattr(a.subprocess, 'run', run)
    assert a._committee_call_claude_cli('role', 'request') == 'READY'
    env = run.call_args.kwargs['env']
    assert 'ANTHROPIC_API_KEY' not in env and 'ANTHROPIC_AUTH_TOKEN' not in env
    assert env['CLAUDE_CODE_OAUTH_TOKEN'] == 'subscription'
    cmd = run.call_args.args[0]
    assert cmd[cmd.index('--tools') + 1] == ''
    assert '--strict-mcp-config' in cmd and '--no-session-persistence' in cmd


@pytest.mark.parametrize('message, expected', [('OAuth token expired', '구독 로그인'), ('You have hit your usage limit', '사용 한도'), ('', '응답 실패')])
def test_cli_failures_are_actionable(linux_cli, monkeypatch, message, expected):
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'subscription')
    proc = MagicMock(returncode=1, stdout=json.dumps({'result': message, 'is_error': True}).encode(), stderr=b'')
    monkeypatch.setattr(a.subprocess, 'run', MagicMock(return_value=proc))
    with pytest.raises(RuntimeError, match=expected):
        a._committee_call_claude_cli('role', 'request')


def test_empty_input_still_rejected(linux_cli):
    assert TestClient(a.app).post('/api/generate-claude', json={'sector': '  '}).status_code == 400
