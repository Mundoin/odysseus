"""
Schema-shape tests for external-action tool guardrails.

Kept in a separate file from test_external_action_guards.py to avoid
the tool_schemas ↔ agent_tools circular-import poisoning that occurs when
tool_implementations is imported in the same pytest session.
"""
import pytest

# agent_tools must be fully loaded before tool_schemas is imported; otherwise
# the tool_schemas → agent_tools → tool_schemas circular dependency causes
# FUNCTION_TOOL_SCHEMAS to be unavailable in agent_tools' import of tool_schemas.
# Importing agent_tools here ensures it is in sys.modules first.
from src import agent_tools as _ag  # noqa: F401

pytestmark = [pytest.mark.area_security, pytest.mark.sub_external_action_guards]


def _get_schema(name: str) -> dict:
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    for s in FUNCTION_TOOL_SCHEMAS:
        if s.get("function", {}).get("name") == name:
            return s["function"]
    raise KeyError(f"{name!r} not found in FUNCTION_TOOL_SCHEMAS")


class TestExternalActionSchemas:
    def test_api_call_has_confirmed_property(self):
        fn = _get_schema("api_call")
        assert "confirmed" in fn["parameters"]["properties"]

    def test_api_call_confirmed_is_boolean(self):
        fn = _get_schema("api_call")
        assert fn["parameters"]["properties"]["confirmed"]["type"] == "boolean"

    def test_api_call_confirmed_not_required(self):
        fn = _get_schema("api_call")
        assert "confirmed" not in fn["parameters"].get("required", [])

    def test_app_api_has_confirmed_property(self):
        fn = _get_schema("app_api")
        assert "confirmed" in fn["parameters"]["properties"]

    def test_app_api_confirmed_is_boolean(self):
        fn = _get_schema("app_api")
        assert fn["parameters"]["properties"]["confirmed"]["type"] == "boolean"

    def test_app_api_confirmed_not_required(self):
        fn = _get_schema("app_api")
        assert "confirmed" not in fn["parameters"].get("required", [])

    def test_api_call_description_mentions_confirmation(self):
        fn = _get_schema("api_call")
        assert "confirmed=true" in fn["description"]

    def test_app_api_description_mentions_confirmation(self):
        fn = _get_schema("app_api")
        assert "confirmed=true" in fn["description"]
