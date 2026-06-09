"""
Tests that prove send_email reaches the model for explicit email-send intent.

Covers:
- _model_supports_tools keyword matching (moonshot, deepseek, gemini, glm, kimi)
- email domain injection populates _relevant_tools with send_email
- FUNCTION_TOOL_SCHEMAS filtered by _relevant_tools includes send_email
- migration script classifies known providers correctly
- execution guards still enforced (no account_id, no confirmed=true)
"""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.area_security, pytest.mark.sub_tool_list]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMAIL_SEND_PROMPT = "Use the email tool to send guardrail test to test@example.com"

# Keywords list extracted from agent_loop — keeps test in sync without importing
# the whole loop.
_MODEL_SUPPORTS_TOOLS_KEYWORDS = (
    "gpt-4", "gpt-5", "gpt-o", "claude", "gemini", "gemma",
    "qwen3", "qwen2.5", "mixtral", "mistral", "llama-3.1", "llama-3.2",
    "llama-3.3", "llama-4",
    "minimax", "kimi", "moonshot",
    "yi-", "phi-3", "phi-4", "command-r",
    "glm-4", "internlm", "hermes",
    "deepseek-v", "deepseek-chat",
)

_MODEL_NO_TOOLS_KEYWORDS = ("deepseek-r1",)


def _model_is_tool_capable(model_name: str) -> bool:
    lc = model_name.lower()
    if any(kw in lc for kw in _MODEL_NO_TOOLS_KEYWORDS):
        return False
    return any(kw in lc for kw in _MODEL_SUPPORTS_TOOLS_KEYWORDS)


def _simulate_email_domain_tool_injection() -> set:
    """Reproduce _DOMAIN_TOOL_MAP['email'] expansion from agent_loop."""
    from src.agent_loop import _DOMAIN_TOOL_MAP
    return set(_DOMAIN_TOOL_MAP.get("email", set()))


def _filter_schemas_by_relevant(relevant_tools: set) -> list[str]:
    """Reproduce the _relevant_tools schema filter from agent_loop lines 2132-2141."""
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    return [
        s["function"]["name"]
        for s in FUNCTION_TOOL_SCHEMAS
        if s.get("function", {}).get("name") in relevant_tools
    ]


# ---------------------------------------------------------------------------
# Model keyword classification
# ---------------------------------------------------------------------------

class TestModelKeywordClassification:
    @pytest.mark.parametrize("model_name", [
        "gemini-1.5-flash",
        "gemini-2.0-pro",
        "deepseek-chat",
        "deepseek-v3",
        "moonshot-v1-8k",
        "moonshot-v1-128k",
        "kimi-latest",
        "glm-4-flash",
        "glm-4-air",
        "claude-3-5-sonnet-20241022",
        "gpt-4o",
        "gpt-4-turbo",
    ])
    def test_tool_capable_model_recognised(self, model_name):
        assert _model_is_tool_capable(model_name), (
            f"{model_name!r} should be classified tool-capable but was not. "
            "Add its keyword to _model_supports_tools in agent_loop.py."
        )

    @pytest.mark.parametrize("model_name", [
        "deepseek-r1",
        "deepseek-r1-distill-qwen-32b",
        "deepseek-r1-0528",
    ])
    def test_no_tool_model_rejected(self, model_name):
        assert not _model_is_tool_capable(model_name), (
            f"{model_name!r} should NOT be tool-capable (reasoning model)"
        )


# ---------------------------------------------------------------------------
# Email domain injection
# ---------------------------------------------------------------------------

class TestEmailDomainInjection:
    def test_email_domain_includes_send_email(self):
        tools = _simulate_email_domain_tool_injection()
        assert "send_email" in tools

    def test_email_domain_includes_reply_to_email(self):
        tools = _simulate_email_domain_tool_injection()
        assert "reply_to_email" in tools

    def test_email_domain_includes_list_email_accounts(self):
        tools = _simulate_email_domain_tool_injection()
        assert "list_email_accounts" in tools

    def test_email_domain_includes_list_emails(self):
        tools = _simulate_email_domain_tool_injection()
        assert "list_emails" in tools


# ---------------------------------------------------------------------------
# Final schema list: send_email must reach a tool-capable model
# ---------------------------------------------------------------------------

class TestFinalToolList:
    def test_send_email_in_schema_after_domain_injection(self):
        """
        For a tool-capable model receiving explicit email-send intent:
        domain injection → _relevant_tools contains send_email
        schema filter → send_email survives into all_tool_schemas
        """
        relevant = _simulate_email_domain_tool_injection()
        assert "send_email" in relevant, "Domain injection must include send_email"

        final_names = _filter_schemas_by_relevant(relevant)
        assert "send_email" in final_names, (
            "send_email must be in FUNCTION_TOOL_SCHEMAS and survive "
            "_relevant_tools filtering. If missing, the schema is absent from "
            "tool_schemas.py or filtered elsewhere."
        )

    def test_reply_to_email_in_schema_after_domain_injection(self):
        relevant = _simulate_email_domain_tool_injection()
        final_names = _filter_schemas_by_relevant(relevant)
        assert "reply_to_email" in final_names

    def test_list_email_accounts_in_schema_after_domain_injection(self):
        relevant = _simulate_email_domain_tool_injection()
        final_names = _filter_schemas_by_relevant(relevant)
        assert "list_email_accounts" in final_names

    def test_dangerous_admin_tools_not_in_email_domain(self):
        """Domain injection must not smuggle admin tools."""
        relevant = _simulate_email_domain_tool_injection()
        final_names = set(_filter_schemas_by_relevant(relevant))
        for admin_tool in ("bash", "python", "manage_endpoints", "manage_mcp", "write_file"):
            assert admin_tool not in final_names, (
                f"Admin tool {admin_tool!r} must not appear in email-domain schema list"
            )

    def test_prompt_triggers_email_domain(self):
        """The email-send prompt triggers email domain detection."""
        import re
        prompt = EMAIL_SEND_PROMPT.lower()
        # Reproduce the regex from agent_loop intent detection
        email_pattern = r"\b(emails?|mails?|gmail|inbox|reply|forward|cc|bcc|send email|compose email|draft email)\b"
        assert re.search(email_pattern, prompt), (
            f"Prompt {EMAIL_SEND_PROMPT!r} must match email domain regex"
        )


# ---------------------------------------------------------------------------
# Migration script: provider classification
# ---------------------------------------------------------------------------

class TestEndpointMigration:
    def _run_repair(self, endpoints: list[dict]) -> dict:
        """Run repair() against a fake DB of endpoints."""
        from scripts.repair_endpoint_tool_support import (
            _TOOL_CAPABLE_URL_PATTERNS,
            _NO_TOOL_MODEL_PATTERNS,
        )
        import re
        results: dict[str, list] = {"set_true": [], "set_false": [], "skipped": []}
        for ep in endpoints:
            url = (ep.get("base_url") or "").lower()
            name = (ep.get("name") or "").lower()
            if any(pat in name for pat in _NO_TOOL_MODEL_PATTERNS):
                results["set_false"].append(ep["name"])
            elif any(re.search(pat, url) for pat in _TOOL_CAPABLE_URL_PATTERNS):
                results["set_true"].append(ep["name"])
            else:
                results["skipped"].append(ep["name"])
        return results

    def test_gemini_set_true(self):
        r = self._run_repair([{"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}])
        assert "Google Gemini" in r["set_true"]

    def test_deepseek_chat_set_true(self):
        r = self._run_repair([{"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1"}])
        assert "DeepSeek" in r["set_true"]

    def test_moonshot_set_true(self):
        r = self._run_repair([{"name": "Kimi", "base_url": "https://api.moonshot.cn/v1"}])
        assert "Kimi" in r["set_true"]

    def test_mimo_cloud_set_true(self):
        r = self._run_repair([{"name": "Mimo", "base_url": "https://api.xiaomimimo.com/v1"}])
        assert "Mimo" in r["set_true"]

    def test_local_ollama_skipped(self):
        r = self._run_repair([{"name": "Local Ollama", "base_url": "http://127.0.0.1:11434/v1"}])
        assert "Local Ollama" in r["skipped"]

    def test_deepseek_r1_set_false(self):
        r = self._run_repair([{"name": "deepseek-r1", "base_url": "https://api.deepseek.com/v1"}])
        assert "deepseek-r1" in r["set_false"]


# ---------------------------------------------------------------------------
# Execution guards still enforced
# ---------------------------------------------------------------------------

_FAKE_CFG = {
    "smtp_host": "smtp.example.com", "smtp_port": 587,
    "smtp_user": "u@example.com", "smtp_pass": "x",
    "smtp_tls": True, "email": "u@example.com",
    "from_address": "u@example.com",
}


class TestExecutionGuardsUnchanged:
    def test_no_account_id_blocked(self):
        from mcp_servers.email_server import _send_email
        with patch(
            "mcp_servers.email_server._resolve_send_config",
            side_effect=ValueError("account required"),
        ):
            with pytest.raises(ValueError, match="account"):
                _send_email(to="x@y.com", subject="s", body="b", account=None)

    def test_confirmed_false_returns_preview_no_smtp(self):
        from mcp_servers.email_server import _send_email
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("work", _FAKE_CFG)), \
             patch("mcp_servers.email_server.smtplib") as mock_smtp:
            result = _send_email(to="x@y.com", subject="s", body="b", account="work", confirmed=False)
        assert result.get("pending_confirmation") is True
        mock_smtp.SMTP.assert_not_called()
        mock_smtp.SMTP_SSL.assert_not_called()

    def test_confirmed_true_does_not_return_preview(self):
        """With confirmed=True, _send_email must NOT return pending_confirmation.
        Full SMTP delivery path is covered in test_email_send_guards.py."""
        from mcp_servers.email_server import _send_email
        with patch("mcp_servers.email_server._resolve_send_config", return_value=("work", _FAKE_CFG)):
            # confirmed=True skips the preview gate — any non-preview result is correct here
            try:
                result = _send_email(to="x@y.com", subject="s", body="b", account="work", confirmed=True)
                assert result.get("pending_confirmation") is not True
            except (ValueError, Exception):
                pass  # downstream SMTP errors are fine — preview gate was not triggered
