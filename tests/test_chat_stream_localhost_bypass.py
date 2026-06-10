"""LOCALHOST_BYPASS must cover the chat_stream session-owner check.

Live smoke previously needed AUTH_ENABLED=false because
`_verify_session_owner` 401'd loopback callers that the middleware's
LOCALHOST_BYPASS had already let through.

Matrix pinned here:
- bypass on  + loopback     → allowed
- bypass on  + non-loopback → ownership still enforced (401)
- bypass off                → existing rules unchanged (401)
- AUTH_ENABLED=false        → existing disabled-auth behaviour unchanged
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

pytestmark = [pytest.mark.area_security, pytest.mark.sub_chat_stream_localhost_bypass]

from src.auth_helpers import localhost_bypass_active
from routes import session_routes


def _request(host, user=None):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        state=SimpleNamespace(current_user=user, api_token=False),
    )


def _patch_db_row(monkeypatch, owner="bujar", exists=True):
    db = MagicMock()
    row = SimpleNamespace(owner=owner) if exists else None
    db.query.return_value.filter.return_value.first.return_value = row
    monkeypatch.setattr(session_routes, "SessionLocal", MagicMock(return_value=db))


def test_bypass_on_loopback_allows_chat_stream_owner_check(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _patch_db_row(monkeypatch, owner="bujar")
    # no exception — loopback caller passes despite no authenticated user
    session_routes._verify_session_owner(_request("127.0.0.1"), "sid-1")


@pytest.mark.parametrize("host", ["::1", "localhost"])
def test_bypass_on_other_loopback_hosts(monkeypatch, host):
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _patch_db_row(monkeypatch)
    session_routes._verify_session_owner(_request(host), "sid-1")


def test_bypass_on_non_loopback_still_401(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _patch_db_row(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        session_routes._verify_session_owner(_request("192.168.1.50"), "sid-1")
    assert exc.value.status_code == 401


def test_bypass_off_loopback_still_401(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "false")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _patch_db_row(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        session_routes._verify_session_owner(_request("127.0.0.1"), "sid-1")
    assert exc.value.status_code == 401


def test_authenticated_user_ownership_still_enforced_with_bypass(monkeypatch):
    # A logged-in user must never read another owner's session, bypass or not.
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _patch_db_row(monkeypatch, owner="bob")
    with pytest.raises(HTTPException) as exc:
        session_routes._verify_session_owner(_request("127.0.0.1", user="alice"), "sid-1")
    assert exc.value.status_code == 404


def test_auth_disabled_behaviour_unchanged(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _patch_db_row(monkeypatch, owner="bujar")
    session_routes._verify_session_owner(_request("10.0.0.5"), "sid-1")


def test_localhost_bypass_active_helper(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    assert localhost_bypass_active(_request("127.0.0.1")) is True
    assert localhost_bypass_active(_request("::1")) is True
    assert localhost_bypass_active(_request("8.8.8.8")) is False
    monkeypatch.setenv("LOCALHOST_BYPASS", "false")
    assert localhost_bypass_active(_request("127.0.0.1")) is False
