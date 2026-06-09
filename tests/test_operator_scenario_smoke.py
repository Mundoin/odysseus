"""Operator scenario smoke tests for the hardened local fork.

These tests exercise realistic user-facing flows with mocked/local-safe
execution only. They intentionally avoid real email, browser, network, remotes,
or destructive actions.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.area_security, pytest.mark.sub_operator_scenario_smoke]


def _fake_email_cfg():
    return {
        "account_name": "work",
        "account_id": "acc-1",
        "from_address": "work@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "work@example.com",
        "smtp_password": "REDACTED",
        "smtp_security": "starttls",
    }


def _fake_skill_manager(skills=None):
    sm = MagicMock()
    sm.load.return_value = skills or [{"name": "existing-skill", "status": "draft"}]
    sm.add_skill.return_value = {"name": "new-skill", "status": "draft"}
    sm.update_skill.return_value = True
    sm.delete_skill.return_value = True
    sm.read_skill_md.return_value = "# existing-skill\n\nDo the thing."
    sm.get_relevant_skills.return_value = [{"name": "existing-skill"}]
    return sm


async def _call_manage_skills(payload, skill_manager):
    from src.tool_implementations import do_manage_skills

    with patch("services.memory.skills.SkillsManager", return_value=skill_manager), \
         patch("src.constants.DATA_DIR", "/fake"):
        return await do_manage_skills(json.dumps(payload), owner="mundoin")


async def _dispatch_mcp(tool, args, call_tool):
    from src.external_action_guard import guard_mcp

    forwarded_args = dict(args)
    confirmed = bool(forwarded_args.pop("confirmed", False))
    preview = guard_mcp(tool, forwarded_args, confirmed)
    if preview is not None:
        return preview
    return await call_tool(tool, forwarded_args)


def test_email_operator_flow_preview_blocks_send_and_confirmed_path_sends():
    from mcp_servers.email_server import _send_email

    fake_cfg = _fake_email_cfg()
    with patch("mcp_servers.email_server._resolve_send_config", return_value=("acc-1", fake_cfg)), \
         patch("mcp_servers.email_server._smtp_connect") as smtp_connect:
        preview = _send_email(
            to="dest@example.com",
            subject="Operator smoke",
            body="Draft body for operator review",
            account="work",
            confirmed=False,
        )

    smtp_connect.assert_not_called()
    assert preview["pending_confirmation"] is True
    assert preview["confirmation_required"] is True
    assert preview["tool_name"] == "send_email"
    assert preview["action_name"] == "send_email"
    assert preview["from"] == "work@example.com"
    assert preview["to"] == "dest@example.com"
    assert preview["subject"] == "Operator smoke"
    assert "Draft body" in preview["body_preview"]
    assert "externally visible email" in preview["consequences"]
    assert "confirmed=true" in preview["approval_instruction"]
    assert preview["high_impact"] is True
    assert isinstance(preview["final_review_checklist"], list)

    smtp_conn = MagicMock()
    with patch("mcp_servers.email_server._resolve_send_config", return_value=("acc-1", fake_cfg)), \
         patch("mcp_servers.email_server._smtp_connect", return_value=smtp_conn), \
         patch("mcp_servers.email_server._imap_connect", side_effect=Exception("no imap in smoke")):
        sent = _send_email(
            to="dest@example.com",
            subject="Operator smoke",
            body="Draft body for operator review",
            account="work",
            confirmed=True,
        )

    smtp_conn.send_message.assert_called_once()
    assert sent.get("sent") is True
    assert "pending_confirmation" not in sent


@pytest.mark.asyncio
async def test_skill_operator_flow_allows_reads_blocks_mutations_and_confirms_local_mutation():
    sm = _fake_skill_manager()

    listed = await _call_manage_skills({"action": "list"}, sm)
    viewed = await _call_manage_skills({"action": "view", "name": "existing-skill"}, sm)
    searched = await _call_manage_skills({"action": "search", "query": "existing"}, sm)
    assert "pending_confirmation" not in listed
    assert "pending_confirmation" not in viewed
    assert "pending_confirmation" not in searched

    add_preview = await _call_manage_skills(
        {"action": "add", "name": "new-skill", "description": "safe local draft"},
        sm,
    )
    edit_preview = await _call_manage_skills(
        {"action": "edit", "name": "existing-skill", "content": "# updated"},
        sm,
    )
    delete_preview = await _call_manage_skills(
        {"action": "delete", "name": "existing-skill"},
        sm,
    )

    for preview in (add_preview, edit_preview, delete_preview):
        assert preview["pending_confirmation"] is True
        assert preview["confirmation_required"] is True
        assert preview["tool_name"] == "manage_skills"
        assert preview["target_resource"].startswith("skill:")
        assert "local skill registry" in preview["consequences"]
        assert "confirmed=true" in preview["approval_instruction"]
        assert preview["high_impact"] is False

    assert add_preview["target"] == "new-skill"
    assert delete_preview["target_resource"] == "skill:existing-skill"
    sm.add_skill.assert_not_called()
    sm.update_skill.assert_not_called()
    sm.delete_skill.assert_not_called()

    confirmed = await _call_manage_skills(
        {
            "action": "add",
            "name": "new-skill",
            "description": "safe local draft",
            "procedure": ["step"],
            "confirmed": True,
        },
        sm,
    )
    sm.add_skill.assert_called_once()
    assert "pending_confirmation" not in confirmed


def test_external_api_operator_flow_allows_reads_and_blocks_risky_write_until_confirmed():
    from src.external_action_guard import guard

    assert guard(
        tool="api_call",
        method="GET",
        target="https://api.example.test/search?q=status",
        confirmed=False,
    ) is None

    preview = guard(
        tool="api_call",
        method="POST",
        target="https://shop.example.test/api/payment/charge",
        confirmed=False,
        body={"amount": 9.99, "currency": "USD"},
        integration="Shop",
    )
    assert preview["pending_confirmation"] is True
    assert preview["target_domain"] == "shop.example.test"
    assert preview["target_url"] == "https://shop.example.test/api/payment/charge"
    assert preview["risk_level"] == "high"
    assert preview["high_impact"] is True
    assert "payment" in preview["high_impact_reason"]
    assert "If approved" in preview["consequences"]
    assert "confirmed=true" in preview["approval_instruction"]
    assert isinstance(preview["final_review_checklist"], list)

    assert guard(
        tool="api_call",
        method="POST",
        target="https://shop.example.test/api/payment/charge",
        confirmed=True,
        body={"amount": 9.99, "currency": "USD"},
        integration="Shop",
    ) is None


@pytest.mark.asyncio
async def test_browser_mcp_operator_flow_allows_read_and_prepare_but_blocks_risky_action_until_confirmed():
    read_call = AsyncMock(return_value={"content": "snapshot"})
    read_result = await _dispatch_mcp("mcp__playwright__browser_snapshot", {}, read_call)
    read_call.assert_awaited_once()
    assert "pending_confirmation" not in read_result

    prepare_call = AsyncMock(return_value={"content": "typed"})
    prepare_result = await _dispatch_mcp(
        "mcp__playwright__browser_fill",
        {"value": "draft text"},
        prepare_call,
    )
    prepare_call.assert_awaited_once()
    assert "pending_confirmation" not in prepare_result

    risky_call = AsyncMock(return_value={"content": "clicked"})
    blocked = await _dispatch_mcp(
        "mcp__playwright__browser_click",
        {"element": "Submit payment"},
        risky_call,
    )
    risky_call.assert_not_called()
    assert blocked["pending_confirmation"] is True
    assert blocked["tool_name"] == "mcp__playwright__browser_click"
    assert blocked["action_name"] == "browser_click"
    assert blocked["target"] == "Submit payment"
    assert blocked["risk_level"] == "high"
    assert blocked["high_impact"] is True
    assert "Approval is required" in blocked["summary"]
    assert "confirmed=true" in blocked["approval_instruction"]
    assert isinstance(blocked["final_review_checklist"], list)

    forwarded = []

    async def confirmed_call(tool, args):
        forwarded.append(dict(args))
        return {"content": "clicked"}

    confirmed = await _dispatch_mcp(
        "mcp__playwright__browser_click",
        {"element": "Submit payment", "confirmed": True},
        confirmed_call,
    )
    assert "pending_confirmation" not in confirmed
    assert forwarded == [{"element": "Submit payment"}]
