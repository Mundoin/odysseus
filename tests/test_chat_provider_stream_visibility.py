"""Regression coverage for visible provider retry/fallback chat events.

These checks pin the app-level contract around provider stream failures without
booting the full UI: retries/fallbacks must not be invisible, and partial text
must not vanish without an interrupted marker.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_chat_routes_forwards_provider_lifecycle_events():
    src = _read("routes/chat_routes.py")
    assert "_PROVIDER_RUNTIME_EVENTS" in src
    assert "provider_retry_start" in src
    assert "provider_fallback_selected" in src
    assert "provider_fallback_start" in src
    assert "model_switch_visible_event" in src
    assert "provider_events" in src


def test_chat_routes_preserves_partial_on_provider_stream_error():
    src = _read("routes/chat_routes.py")
    assert "Provider stream disconnected before finalization" in src
    assert "partial_response_preserved" in src
    assert "assistant_message_finalized" in src
    assert "message_saved" in src


def test_frontend_handles_provider_lifecycle_events():
    src = _read("static/js/chat.js")
    assert "model_switch_visible_event" in src
    assert "provider_stream_error" in src
    assert "provider_fallback_selected" in src
    assert "Provider stream disconnected. Preserving partial response." in src
