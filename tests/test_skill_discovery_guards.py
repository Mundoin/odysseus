"""
Tests for skill discovery guardrails (manage_skills tool):
- Safe actions (list, view, view_ref, search) never blocked
- Mutating actions (add, edit, patch, publish, delete) return preview when confirmed missing/false
- Mutating actions proceed only with confirmed=true
- Internal/teacher-escalation path (confirmed=true in args) is not blocked
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = [pytest.mark.area_services, pytest.mark.sub_skill_guards]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_sm(skills=None):
    sm = MagicMock()
    sm.load.return_value = skills or []
    sm.add_skill.return_value = {"name": "test-skill", "status": "draft"}
    sm.update_skill.return_value = True
    sm.delete_skill.return_value = True
    sm.read_skill_md.return_value = "# test-skill\nsome content"
    sm.get_relevant_skills.return_value = []
    return sm


def _args(**kwargs) -> str:
    return json.dumps(kwargs)


async def _call(args_str: str, sm, owner="mundoin"):
    from src.tool_implementations import do_manage_skills
    # SkillsManager is imported locally inside do_manage_skills — patch at source.
    with patch("services.memory.skills.SkillsManager", return_value=sm), \
         patch("src.constants.DATA_DIR", "/fake"):
        return await do_manage_skills(args_str, owner=owner)


# ---------------------------------------------------------------------------
# Safe discovery actions — never blocked regardless of confirmed
# ---------------------------------------------------------------------------

class TestSafeActions:
    @pytest.mark.asyncio
    async def test_list_no_confirmed_allowed(self):
        sm = _fake_sm()
        result = await _call(_args(action="list"), sm)
        assert "error" not in result
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_index_no_confirmed_allowed(self):
        sm = _fake_sm()
        result = await _call(_args(action="index"), sm)
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_view_no_confirmed_allowed(self):
        sm = _fake_sm()
        result = await _call(_args(action="view", name="my-skill"), sm)
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_search_no_confirmed_allowed(self):
        sm = _fake_sm()
        result = await _call(_args(action="search", query="deployment"), sm)
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_view_ref_no_confirmed_allowed(self):
        sm = _fake_sm()
        sm.read_skill_reference.return_value = "ref content"
        result = await _call(_args(action="view_ref", name="my-skill", path="examples.md"), sm)
        assert "pending_confirmation" not in result


# ---------------------------------------------------------------------------
# Mutating actions without confirmed — must return preview
# ---------------------------------------------------------------------------

class TestMutatingActionsPreview:
    @pytest.mark.asyncio
    async def test_add_without_confirmed_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(
            action="add", name="new-skill",
            description="does something", procedure=["step1"],
        ), sm)
        assert result.get("pending_confirmation") is True
        assert result["action"] == "add"
        sm.add_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_confirmed_false_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(
            action="add", name="new-skill",
            description="desc", procedure=["step1"], confirmed=False,
        ), sm)
        assert result.get("pending_confirmation") is True
        sm.add_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_without_confirmed_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(
            action="edit", name="existing-skill",
            content="# existing-skill\n---\ndesc: x\n---\n",
        ), sm)
        assert result.get("pending_confirmation") is True
        assert "change_summary" in result
        sm.update_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_patch_without_confirmed_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(
            action="patch", name="existing-skill",
            old_string="old text", new_string="new text",
        ), sm)
        assert result.get("pending_confirmation") is True
        assert "change_summary" in result
        sm.update_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_without_confirmed_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(action="publish", name="draft-skill"), sm)
        assert result.get("pending_confirmation") is True
        assert "status_change" in result
        sm.update_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_without_confirmed_returns_preview(self):
        sm = _fake_sm()
        result = await _call(_args(action="delete", name="old-skill"), sm)
        assert result.get("pending_confirmation") is True
        assert "warning" in result
        sm.delete_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_includes_instruction(self):
        sm = _fake_sm()
        result = await _call(_args(action="delete", name="old-skill"), sm)
        assert "instruction" in result
        assert "confirmed=true" in result["instruction"]


# ---------------------------------------------------------------------------
# Mutating actions with confirmed=true — must execute
# ---------------------------------------------------------------------------

class TestMutatingActionsConfirmed:
    @pytest.mark.asyncio
    async def test_add_confirmed_calls_add_skill(self):
        sm = _fake_sm()
        with patch("src.tool_implementations._load_prefs", return_value={}, create=True):
            result = await _call(_args(
                action="add", name="new-skill",
                description="desc", procedure=["step1"], confirmed=True,
            ), sm)
        sm.add_skill.assert_called_once()
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_delete_confirmed_calls_delete_skill(self):
        sm = _fake_sm()
        result = await _call(_args(
            action="delete", name="old-skill", confirmed=True,
        ), sm)
        sm.delete_skill.assert_called_once_with("old-skill", owner="mundoin")
        assert "pending_confirmation" not in result

    @pytest.mark.asyncio
    async def test_publish_confirmed_calls_update_skill(self):
        sm = _fake_sm(skills=[{"name": "draft-skill", "status": "draft"}])
        result = await _call(_args(
            action="publish", name="draft-skill", confirmed=True,
        ), sm)
        sm.update_skill.assert_called_once()
        assert "pending_confirmation" not in result


# ---------------------------------------------------------------------------
# Internal / teacher-escalation path — confirmed=true in JSON args
# ---------------------------------------------------------------------------

class TestInternalConfirmedBypass:
    @pytest.mark.asyncio
    async def test_teacher_escalation_payload_confirmed_executes(self):
        """Teacher escalation sets confirmed=True in the JSON; must not be blocked."""
        sm = _fake_sm()
        teacher_payload = {
            "action": "add",
            "name": "auto-skill",
            "description": "auto-generated",
            "procedure": ["step1"],
            "source": "teacher-escalation",
            "confirmed": True,
        }
        result = await _call(json.dumps(teacher_payload), sm)
        sm.add_skill.assert_called_once()
        assert "pending_confirmation" not in result
