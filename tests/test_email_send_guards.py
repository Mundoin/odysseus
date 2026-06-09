"""
Tests for email send guards:
- _send_email requires explicit account (no silent fallback)
- _send_email returns preview when confirmed=False
- _send_email sends only when confirmed=True
- _resolve_send_config in routes raises when account_id is None
- HTTP POST /api/email/send preview/confirm flow
- HTTP send blocked on missing account_id
- HTTP send blocked on mismatched from_address
"""
import pytest
import sys
import types
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.area_services, pytest.mark.sub_email_send_guards]


# ---------------------------------------------------------------------------
# Helpers — stub out DB and SMTP so no real connections are made
# ---------------------------------------------------------------------------

def _make_fake_cfg(account_name="work", account_id="acc-1", from_address="work@example.com"):
    return {
        "account_name": account_name,
        "account_id": account_id,
        "from_address": from_address,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "work@example.com",
        "smtp_password": "REDACTED",
        "smtp_security": "starttls",
    }


# ---------------------------------------------------------------------------
# mcp_servers.email_server._send_email
# ---------------------------------------------------------------------------

class TestMcpSendEmailGuards:
    def _import_send_email(self):
        """Import _send_email with _resolve_send_config and _smtp_connect stubbed."""
        import importlib
        import mcp_servers.email_server as mod
        return mod._send_email, mod

    def test_no_account_raises(self):
        """Omitting account must raise ValueError listing available accounts."""
        with patch("mcp_servers.email_server._list_smtp_account_names", return_value=["work", "personal"]):
            _send_email, _ = self._import_send_email()
            with pytest.raises(ValueError, match="sender account not specified"):
                _send_email(to="x@example.com", subject="Hi", body="Hello", account=None)

    def test_no_account_lists_available(self):
        """Error message must include available account names."""
        with patch("mcp_servers.email_server._list_smtp_account_names", return_value=["work", "personal"]):
            _send_email, _ = self._import_send_email()
            with pytest.raises(ValueError, match="work"):
                _send_email(to="x@example.com", subject="Hi", body="Hello", account=None)

    def test_unconfirmed_returns_preview_not_sending(self):
        """confirmed=False must return preview dict without touching SMTP."""
        fake_cfg = _make_fake_cfg()
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("acc-1", fake_cfg)), \
             patch("mcp_servers.email_server._smtp_connect") as mock_smtp:
            _send_email, _ = self._import_send_email()
            result = _send_email(
                to="dest@example.com",
                subject="Test subject",
                body="Hello world",
                account="work",
                confirmed=False,
            )
        mock_smtp.assert_not_called()
        assert result["pending_confirmation"] is True
        assert result["from"] == "work@example.com"
        assert result["subject"] == "Test subject"
        assert "instruction" in result

    def test_unconfirmed_body_preview_truncated(self):
        """Body longer than 500 chars must be truncated in preview."""
        fake_cfg = _make_fake_cfg()
        long_body = "x" * 600
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("acc-1", fake_cfg)), \
             patch("mcp_servers.email_server._smtp_connect"):
            _send_email, _ = self._import_send_email()
            result = _send_email(
                to="dest@example.com", subject="S", body=long_body,
                account="work", confirmed=False,
            )
        assert result["body_preview"].endswith("…")
        assert len(result["body_preview"]) <= 502  # 500 chars + ellipsis

    def test_confirmed_true_calls_smtp(self):
        """confirmed=True must proceed to SMTP delivery."""
        fake_cfg = _make_fake_cfg()
        mock_conn = MagicMock()
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("acc-1", fake_cfg)), \
             patch("mcp_servers.email_server._smtp_connect", return_value=mock_conn), \
             patch("mcp_servers.email_server._imap_connect", side_effect=Exception("no imap needed")):
            _send_email, _ = self._import_send_email()
            result = _send_email(
                to="dest@example.com",
                subject="Test",
                body="Hello",
                account="work",
                confirmed=True,
            )
        mock_conn.send_message.assert_called_once()
        assert result.get("sent") is True

    def test_account_mismatch_raises(self):
        """Requesting a non-existent account must raise, not silently use default."""
        with patch("mcp_servers.email_server._resolve_send_config",
                   side_effect=ValueError("account 'ghost' not found")):
            _send_email, _ = self._import_send_email()
            with pytest.raises(ValueError, match="ghost"):
                _send_email(
                    to="dest@example.com", subject="S", body="B",
                    account="ghost", confirmed=True,
                )


# ---------------------------------------------------------------------------
# routes.email_routes._resolve_send_config
# ---------------------------------------------------------------------------

class TestRouteResolveAccountGuard:
    def _import(self):
        import routes.email_routes as mod
        return mod

    def test_no_account_id_raises(self):
        """Passing account_id=None must raise ValueError, not fall back silently."""
        mod = self._import()
        with patch.object(mod, "_list_smtp_account_names_for_owner", return_value=["work"]):
            with pytest.raises(ValueError, match="sender account not specified"):
                mod._resolve_send_config(account_id=None, owner="mundoin")

    def test_no_account_id_error_lists_accounts(self):
        """Error must name available accounts so the caller can present choices."""
        mod = self._import()
        with patch.object(mod, "_list_smtp_account_names_for_owner", return_value=["work", "personal"]):
            with pytest.raises(ValueError, match="work"):
                mod._resolve_send_config(account_id=None, owner="mundoin")

    def test_explicit_account_no_smtp_raises(self):
        """Explicit account with no SMTP config must raise, not fall back."""
        mod = self._import()
        fake_cfg = {"account_name": "readonly", "smtp_host": None, "smtp_user": None, "smtp_password": None}
        with patch.object(mod, "_get_email_config", return_value=fake_cfg):
            with pytest.raises(ValueError, match="no SMTP configured"):
                mod._resolve_send_config(account_id="acc-readonly", owner="mundoin")

    def test_explicit_account_smtp_ready_returns_cfg(self):
        """Explicit account with valid SMTP must be returned as-is."""
        mod = self._import()
        fake_cfg = _make_fake_cfg()
        with patch.object(mod, "_get_email_config", return_value=fake_cfg):
            result = mod._resolve_send_config(account_id="acc-1", owner="mundoin")
        assert result["account_id"] == "acc-1"


# ---------------------------------------------------------------------------
# HTTP POST /api/email/send guard tests (via FastAPI TestClient)
# ---------------------------------------------------------------------------

def _make_test_app():
    """Build a minimal FastAPI app with the email router mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.email_routes as email_mod
    app = FastAPI()
    # mount whatever router the module exposes
    router = email_mod.router if hasattr(email_mod, "router") else None
    if router is None:
        raise RuntimeError("routes.email_routes has no 'router' attribute")
    app.include_router(router, prefix="/api/email")
    return TestClient(app, raise_server_exceptions=True)


class TestHttpSendGuards:
    """HTTP /api/email/send preview/confirm gate."""

    def _build_client(self, mod, raise_exc=False):
        """Call setup_email_routes() with _start_poller stubbed and auth bypassed."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.email_helpers import require_owner
        with patch.object(mod, "_start_poller"):
            router = mod.setup_email_routes()
        app = FastAPI()
        app.include_router(router)
        # Bypass session auth — return a fixed owner string
        app.dependency_overrides[require_owner] = lambda: "mundoin"
        return TestClient(app, raise_server_exceptions=raise_exc)

    def test_missing_account_id_returns_error(self):
        """No account_id must return error listing available accounts."""
        import routes.email_routes as mod
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config",
                          side_effect=ValueError("sender account not specified. Available: work, personal")), \
             patch.object(mod, "_assert_owns_account"):
            resp = client.post(
                "/api/email/send",
                json={"to": "x@example.com", "subject": "Hi", "body": "Hello",
                      "confirmed": False},
            )
        data = resp.json()
        assert data["success"] is False
        assert "account" in data["error"].lower()

    def test_unconfirmed_returns_preview_no_smtp(self):
        """confirmed=False must return pending_confirmation preview, no SMTP."""
        import routes.email_routes as mod
        fake_cfg = _make_fake_cfg()
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config", return_value=fake_cfg), \
             patch.object(mod, "_assert_owns_account"), \
             patch.object(mod, "_send_smtp_message") as mock_send:
            resp = client.post(
                "/api/email/send",
                json={"to": "dest@example.com", "subject": "Test", "body": "Hello",
                      "account_id": "acc-1", "confirmed": False},
            )
        mock_send.assert_not_called()
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert data["from"] == "work@example.com"
        assert data["subject"] == "Test"
        assert "instruction" in data

    def test_confirmed_true_calls_smtp(self):
        """confirmed=True must reach _send_smtp_message."""
        import routes.email_routes as mod
        fake_cfg = _make_fake_cfg()
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config", return_value=fake_cfg), \
             patch.object(mod, "_assert_owns_account"), \
             patch.object(mod, "_send_smtp_message") as mock_send, \
             patch.object(mod, "_imap_connect", side_effect=Exception("no imap")):
            resp = client.post(
                "/api/email/send",
                json={"to": "dest@example.com", "subject": "Test", "body": "Hello",
                      "account_id": "acc-1", "confirmed": True,
                      "wait_for_delivery": True},
            )
        mock_send.assert_called_once()

    def test_mismatched_from_address_blocked(self):
        """from_address that doesn't match resolved SMTP identity must be blocked."""
        import routes.email_routes as mod
        fake_cfg = _make_fake_cfg(from_address="work@example.com")
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config", return_value=fake_cfg), \
             patch.object(mod, "_assert_owns_account"), \
             patch.object(mod, "_send_smtp_message") as mock_send:
            resp = client.post(
                "/api/email/send",
                json={"to": "dest@example.com", "subject": "Hi", "body": "Hello",
                      "account_id": "acc-1", "confirmed": True,
                      "from_address": "personal@example.com"},
            )
        mock_send.assert_not_called()
        data = resp.json()
        assert data["success"] is False
        assert "personal@example.com" in data["error"]

    def test_matching_from_address_allowed(self):
        """from_address matching resolved SMTP identity must not fire mismatch block."""
        import routes.email_routes as mod
        fake_cfg = _make_fake_cfg(from_address="work@example.com")
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config", return_value=fake_cfg), \
             patch.object(mod, "_assert_owns_account"), \
             patch.object(mod, "_send_smtp_message"):
            resp = client.post(
                "/api/email/send",
                json={"to": "dest@example.com", "subject": "Hi", "body": "Hello",
                      "account_id": "acc-1", "confirmed": False,
                      "from_address": "work@example.com"},
            )
        data = resp.json()
        assert data.get("pending_confirmation") is True

    def test_body_preview_truncated_at_500(self):
        """Body longer than 500 chars must be truncated in HTTP preview."""
        import routes.email_routes as mod
        fake_cfg = _make_fake_cfg()
        client = self._build_client(mod)
        with patch.object(mod, "_resolve_send_config", return_value=fake_cfg), \
             patch.object(mod, "_assert_owns_account"):
            resp = client.post(
                "/api/email/send",
                json={"to": "x@example.com", "subject": "S", "body": "x" * 600,
                      "account_id": "acc-1", "confirmed": False},
            )
        data = resp.json()
        assert data["body_preview"].endswith("…")
        assert len(data["body_preview"]) <= 502
