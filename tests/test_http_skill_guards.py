"""
Tests for HTTP skill mutation guards:
- POST /api/skills/add returns preview without confirmed, executes with confirmed=true
- POST /api/skills/import-from-url returns preview without confirmed; never fetches external URL
- POST /api/skills/{id}/markdown returns preview without confirmed
- PUT /api/skills/{id} returns preview without confirmed
- DELETE /api/skills/{id} returns preview without confirmed
- Safe routes (GET list, GET skill, POST search) are never blocked
"""
import json
import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.area_routes, pytest.mark.sub_http_skill_guards]

_FAKE_SKILL = {
    "name": "my-skill",
    "id": "my-skill",
    "description": "does stuff",
    "status": "draft",
    "category": "general",
    "owner": "mundoin",
    "procedure": ["step1"],
    "tags": [],
    "platforms": [],
    "confidence": 0.8,
    "audit_verdict": None,
}


def _fake_sm():
    sm = MagicMock()
    sm.load.return_value = [_FAKE_SKILL]
    sm.add_skill.return_value = {"name": "my-skill", "status": "draft"}
    sm.update_skill.return_value = True
    sm.delete_skill.return_value = True
    sm.read_skill_md.return_value = "# my-skill\nsome content"
    sm.get_relevant_skills.return_value = [_FAKE_SKILL]
    sm.index_for.return_value = [_FAKE_SKILL]
    sm.import_bundle_from_files.return_value = {"name": "imported-skill"}
    return sm


def _build_client(sm):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.skills_routes as mod

    app = FastAPI()
    router = mod.setup_skills_routes(sm)
    app.include_router(router)

    # Bypass auth: make _owner() return "mundoin" and require_admin a no-op
    with patch.object(mod, "get_current_user", return_value="mundoin"), \
         patch.object(mod, "require_admin"):
        client = TestClient(app, raise_server_exceptions=True)
        # Rebind patches to stay active during requests
        app.state._mock_patches = (
            patch.object(mod, "get_current_user", return_value="mundoin"),
            patch.object(mod, "require_admin"),
        )
        for p in app.state._mock_patches:
            p.start()
        yield client
        for p in app.state._mock_patches:
            p.stop()


@pytest.fixture()
def client_sm():
    sm = _fake_sm()
    gen = _build_client(sm)
    client = next(gen)
    yield client, sm
    try:
        next(gen)
    except StopIteration:
        pass


# ---------------------------------------------------------------------------
# POST /api/skills/add
# ---------------------------------------------------------------------------

class TestAddSkillGuard:
    def test_unconfirmed_returns_preview(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/add", json={
            "name": "new-skill", "description": "desc", "procedure": ["s1"],
        })
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert data["action"] == "add"
        sm.add_skill.assert_not_called()

    def test_confirmed_false_returns_preview(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/add", json={
            "name": "new-skill", "confirmed": False,
        })
        assert resp.json().get("pending_confirmation") is True
        sm.add_skill.assert_not_called()

    def test_confirmed_true_creates_skill(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/add", json={
            "name": "new-skill", "description": "desc", "procedure": ["s1"],
            "confirmed": True,
        })
        sm.add_skill.assert_called_once()
        assert resp.json().get("ok") is True

    def test_preview_includes_name(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/add", json={"name": "special-skill"})
        assert "special-skill" in resp.json().get("name", "")

    def test_preview_uses_standard_confirmation_surface(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/add", json={
            "name": "special-skill", "description": "desc", "procedure": ["s1"],
        })
        data = resp.json()
        assert data["confirmation_required"] is True
        assert data["action_category"] == "local_prepare"
        assert data["risk_level"] == "normal"
        assert data["tool_name"] == "skills_api"
        assert data["action_name"] == "add"
        assert data["target"] == "special-skill"
        assert data["target_resource"] == "skill:special-skill"
        assert "special-skill" in data["summary"]
        assert "local skill registry" in data["consequences"]
        assert data["approval_instruction"] == data["instruction"]
        assert data["high_impact"] is False
        assert data["arguments_preview"]["action"] == "add"


# ---------------------------------------------------------------------------
# POST /api/skills/import-from-url
# ---------------------------------------------------------------------------

class TestImportFromUrlGuard:
    def test_unconfirmed_returns_preview_no_fetch(self, client_sm):
        client, sm = client_sm
        with patch("routes.skills_routes.require_admin"):
            resp = client.post("/api/skills/import-from-url", json={
                "url": "https://example.com/skill.zip",
            })
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert data["action"] == "import-from-url"
        sm.import_bundle_from_files.assert_not_called()

    def test_unconfirmed_url_echoed_in_preview(self, client_sm):
        client, sm = client_sm
        with patch("routes.skills_routes.require_admin"):
            resp = client.post("/api/skills/import-from-url", json={
                "url": "https://example.com/my-skill.zip",
            })
        assert "example.com" in resp.json().get("url", "")

    def test_confirmed_true_calls_import(self, client_sm):
        client, sm = client_sm
        fake_files = {"SKILL.md": "# imported-skill\n---\n---\n"}
        with patch("routes.skills_routes.require_admin"), \
             patch("services.memory.skill_importer.fetch_skill_bundle",
                   return_value=(fake_files, "https://example.com/skill.zip")):
            resp = client.post("/api/skills/import-from-url", json={
                "url": "https://example.com/skill.zip",
                "confirmed": True,
            })
        sm.import_bundle_from_files.assert_called_once()
        assert resp.json().get("ok") is True


# ---------------------------------------------------------------------------
# POST /api/skills/{id}/markdown
# ---------------------------------------------------------------------------

class TestSaveMarkdownGuard:
    def test_unconfirmed_returns_preview(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/my-skill/markdown", json={
            "markdown": "# my-skill\n---\ndesc: x\n---\nbody",
        })
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert data["action"] == "save-markdown"
        sm.update_skill.assert_not_called()

    def test_confirmed_true_updates_skill(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/my-skill/markdown", json={
            "markdown": "# my-skill\n---\ndesc: x\n---\nbody",
            "confirmed": True,
        })
        sm.update_skill.assert_called_once()


# ---------------------------------------------------------------------------
# PUT /api/skills/{id}
# ---------------------------------------------------------------------------

class TestUpdateSkillGuard:
    def test_unconfirmed_returns_preview(self, client_sm):
        client, sm = client_sm
        resp = client.put("/api/skills/my-skill", json={"description": "new desc"})
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert data["action"] == "update"
        sm.update_skill.assert_not_called()

    def test_confirmed_true_updates(self, client_sm):
        client, sm = client_sm
        resp = client.put("/api/skills/my-skill", json={
            "description": "new desc", "confirmed": True,
        })
        sm.update_skill.assert_called_once()
        assert resp.json().get("ok") is True

    def test_confirmed_not_passed_to_update_skill(self, client_sm):
        """confirmed field must be stripped before passing to skills_manager."""
        client, sm = client_sm
        client.put("/api/skills/my-skill", json={
            "description": "new desc", "confirmed": True,
        })
        call_kwargs = sm.update_skill.call_args
        updates_arg = call_kwargs[0][1] if call_kwargs[0] else call_kwargs[1].get("updates", {})
        assert "confirmed" not in updates_arg


# ---------------------------------------------------------------------------
# DELETE /api/skills/{id}
# ---------------------------------------------------------------------------

class TestDeleteSkillGuard:
    def test_unconfirmed_returns_preview(self, client_sm):
        client, sm = client_sm
        resp = client.delete("/api/skills/my-skill")
        data = resp.json()
        assert data.get("pending_confirmation") is True
        assert "warning" in data
        sm.delete_skill.assert_not_called()

    def test_confirmed_true_deletes(self, client_sm):
        client, sm = client_sm
        resp = client.delete("/api/skills/my-skill?confirmed=true")
        sm.delete_skill.assert_called_once()
        assert resp.json().get("ok") is True


# ---------------------------------------------------------------------------
# Safe routes — never blocked regardless of confirmed
# ---------------------------------------------------------------------------

class TestSafeRoutesUnblocked:
    def test_list_skills_no_confirmation_needed(self, client_sm):
        client, sm = client_sm
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        assert "pending_confirmation" not in resp.json()

    def test_get_skill_no_confirmation_needed(self, client_sm):
        client, sm = client_sm
        resp = client.get("/api/skills/my-skill")
        assert resp.status_code == 200
        assert "pending_confirmation" not in resp.json()

    def test_search_no_confirmation_needed(self, client_sm):
        client, sm = client_sm
        resp = client.post("/api/skills/search", json={"query": "deployment"})
        assert resp.status_code == 200
        assert "pending_confirmation" not in resp.json()
