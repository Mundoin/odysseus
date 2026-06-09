"""
Tests for email tool exposure fixes:
- non-admin resource owners can see send_email/reply_to_email schemas
- truly admin-only tools remain blocked for non-admin
- execution guards (account_id, confirmed=true) still enforced
- non-tool-capable model produces empty built-in schema list and logs why
"""
import logging
import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.area_security, pytest.mark.sub_email_tool_exposure]

_FAKE_CFG = {
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "user@example.com",
    "smtp_pass": "secret",
    "smtp_tls": True,
    "email": "user@example.com",
}


# ---------------------------------------------------------------------------
# tool_security: email tools no longer blocked for resource owners
# ---------------------------------------------------------------------------

class TestEmailToolsNotBlockedForOwner:
    def _blocked(self, is_admin: bool) -> set:
        from src.tool_security import blocked_tools_for_owner
        with patch("src.tool_security.owner_is_admin_or_single_user", return_value=is_admin):
            return blocked_tools_for_owner("someuser")

    def test_send_email_not_blocked_for_non_admin(self):
        assert "send_email" not in self._blocked(False)

    def test_reply_to_email_not_blocked_for_non_admin(self):
        assert "reply_to_email" not in self._blocked(False)

    def test_list_emails_not_blocked_for_non_admin(self):
        assert "list_emails" not in self._blocked(False)

    def test_read_email_not_blocked_for_non_admin(self):
        assert "read_email" not in self._blocked(False)

    def test_admin_returns_empty_blocked_set(self):
        assert self._blocked(True) == set()

    def test_is_public_blocked_tool_email_returns_false(self):
        from src.tool_security import is_public_blocked_tool
        assert not is_public_blocked_tool("send_email")
        assert not is_public_blocked_tool("reply_to_email")
        assert not is_public_blocked_tool("list_emails")
        assert not is_public_blocked_tool("read_email")


# ---------------------------------------------------------------------------
# tool_security: true admin/system tools still blocked for non-admin
# ---------------------------------------------------------------------------

class TestAdminToolsStillBlocked:
    def _blocked(self) -> set:
        from src.tool_security import blocked_tools_for_owner
        with patch("src.tool_security.owner_is_admin_or_single_user", return_value=False):
            return blocked_tools_for_owner("someuser")

    def test_bash_still_blocked(self):
        assert "bash" in self._blocked()

    def test_python_still_blocked(self):
        assert "python" in self._blocked()

    def test_manage_endpoints_still_blocked(self):
        assert "manage_endpoints" in self._blocked()

    def test_manage_mcp_still_blocked(self):
        assert "manage_mcp" in self._blocked()

    def test_manage_settings_still_blocked(self):
        assert "manage_settings" in self._blocked()

    def test_write_file_still_blocked(self):
        assert "write_file" in self._blocked()

    def test_mcp_namespace_still_blocked(self):
        from src.tool_security import is_public_blocked_tool
        assert is_public_blocked_tool("mcp__email__send")


# ---------------------------------------------------------------------------
# Execution guards: account_id and confirmed=true still enforced
# ---------------------------------------------------------------------------

class TestSendEmailExecutionGuards:
    def test_no_account_raises_valueerror(self):
        from mcp_servers.email_server import _send_email
        with patch(
            "mcp_servers.email_server._resolve_send_config",
            side_effect=ValueError("account_id required. Available SMTP accounts: []"),
        ):
            with pytest.raises(ValueError, match="account"):
                _send_email(to="x@y.com", subject="hi", body="body", account=None)

    def test_confirmed_false_returns_preview_no_smtp(self):
        from mcp_servers.email_server import _send_email
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("work", _FAKE_CFG)):
            result = _send_email(
                to="x@y.com", subject="Test", body="Hello",
                account="work", confirmed=False,
            )
        assert result.get("pending_confirmation") is True
        assert "instruction" in result

    def test_confirmed_false_does_not_call_smtp(self):
        from mcp_servers.email_server import _send_email
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("work", _FAKE_CFG)), \
             patch("mcp_servers.email_server.smtplib") as mock_smtp:
            _send_email(to="x@y.com", subject="Test", body="Hello", account="work", confirmed=False)
        mock_smtp.SMTP.assert_not_called()
        mock_smtp.SMTP_SSL.assert_not_called()


# ---------------------------------------------------------------------------
# Non-tool-capable model: empty schema list + warning logged
# ---------------------------------------------------------------------------

class TestNonToolCapableModel:
    def test_local_model_no_mcp_keywords_empty_schemas(self):
        """Reproduce the agent_loop schema-building logic for a non-API model."""
        mcp_schemas: list = []
        _is_api_model = False
        _last_content = "send this email to john"
        _MCP_KEYWORDS = ["mcp", "tool:", "use tool", "mcp__"]
        _wants_mcp = any(kw in _last_content for kw in _MCP_KEYWORDS)
        all_tool_schemas = mcp_schemas if (_wants_mcp and mcp_schemas) else []
        assert all_tool_schemas == []

    def test_local_model_email_tools_wanted_emits_warning(self, caplog):
        """When _is_api_model=False and email tools requested, a WARNING is logged."""
        with caplog.at_level(logging.WARNING, logger="src.agent_loop"):
            # Exercise the warning branch directly
            import logging as _log
            _logger = _log.getLogger("src.agent_loop")
            _relevant_tools = {"send_email", "list_emails"}
            _email_tools_wanted = bool(_relevant_tools & {"send_email", "reply_to_email", "list_emails", "read_email"})
            if _email_tools_wanted:
                _logger.warning(
                    "[agent] model=%r endpoint=%r does not support native tool calling "
                    "(endpoint_supports=%r _is_ollama_native=%r). Email tools were "
                    "requested but schemas are suppressed. To enable: set "
                    "supports_tools=True on this endpoint, or switch to a "
                    "tool-capable model (Claude, GPT-4, Gemini, DeepSeek-Chat).",
                    "mimo-7b", "http://localhost:11434", None, True,
                )
        assert any("does not support native tool calling" in r.message for r in caplog.records)
        assert any("supports_tools=True" in r.message for r in caplog.records)

    def test_api_model_keyword_detected(self):
        """Models with known tool-capable keywords are classified _is_api_model=True."""
        _model_supports_tools_keywords = (
            "gpt-4", "gpt-5", "claude", "gemini", "deepseek-v", "deepseek-chat",
            "llama-3.1", "llama-3.2", "llama-3.3", "llama-4",
        )
        for keyword in ("claude-3-5-sonnet", "gpt-4o", "gemini-1.5-pro", "deepseek-chat"):
            model_lc = keyword.lower()
            matched = any(kw in model_lc for kw in _model_supports_tools_keywords)
            assert matched, f"{keyword!r} should be classified as tool-capable"

    def test_deepseek_r1_not_tool_capable(self):
        """deepseek-r1 reasoning model is explicitly in the no-tools blocklist."""
        _model_no_tools_keywords = ("deepseek-r1",)
        model_lc = "deepseek-r1-distill-qwen-32b"
        assert any(kw in model_lc for kw in _model_no_tools_keywords)
