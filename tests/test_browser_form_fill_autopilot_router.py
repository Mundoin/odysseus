"""Deterministic approval router for pending browser safe fills.

Stage: odysseus-browser-form-fill-autopilot-router-v1

Proves the execution switch is taken away from the model:
- a pending safe fill + user approval executes backend-side, exactly once,
  with confirmed=true — without any model tool call
- non-approval messages do not execute and keep the pending action
- submit/apply asks are never routed through the safe fill router
- no pending action means no route (normal agent flow)
- expired pending actions are rejected, cleared, and reported
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

pytestmark = [
    pytest.mark.area_security,
    pytest.mark.sub_browser_form_fill_autopilot_router,
]

from src import form_fill_router as router
from src.browser_operator import browser_action_scope

SESSION = "router-test-session"
SCOPE = browser_action_scope(session_id=SESSION)

KNOWN_VALUES = {
    "first_name": "Bujar",
    "last_name": "Smoke",
    "email": "bujar.smoke@example.com",
    "phone": "+49123456789",
    "city": "Dortmund",
    "postcode": "44137",
    "cover_letter": "Short smoke-test cover letter text.",
}
PAGE_URL = "http://127.0.0.1:8765/odysseus-smoke-form.html"


@pytest.fixture(autouse=True)
def _clean_pending():
    router.clear_pending_safe_fill()
    yield
    router.clear_pending_safe_fill()


def _record_pending(**overrides):
    kwargs = dict(page_url=PAGE_URL, known_values=KNOWN_VALUES)
    kwargs.update(overrides)
    return router.record_pending_safe_fill(SCOPE, **kwargs)


def _route(message, execute):
    return asyncio.run(
        router.maybe_route_pending_browser_fill(
            message, session_id=SESSION, execute=execute
        )
    )


# ── 1. Approval routes pending safe fill directly (no model tool call) ─────


def test_approval_executes_backend_directly_exactly_once():
    _record_pending()
    execute = AsyncMock(return_value={"output": "Safe fill completed. 7 fields filled, 0 failed, 0 could not be verified. 0 skipped, 0 blocked.", "exit_code": 0})

    routed = _route("Yes, fill it", execute)

    assert routed is not None
    assert routed["status"] == "executed"
    assert routed["result"]["exit_code"] == 0
    execute.assert_awaited_once()
    args = execute.await_args.args[0]
    assert args["confirmed"] is True
    assert args["page_url"] == PAGE_URL
    assert args["known_values"] == KNOWN_VALUES
    # pending action cleared — approval is not replayable
    assert router.get_pending_safe_fill(SCOPE) is None


@pytest.mark.parametrize(
    "message",
    ["yes", "yes fill it", "approved", "approve", "go ahead", "do it",
     "fill it", "yes!!", "ok", "okay, proceed", "Yes please"],
)
def test_supported_approval_phrasings_route(message):
    _record_pending()
    execute = AsyncMock(return_value={"output": "ok", "exit_code": 0})
    routed = _route(message, execute)
    assert routed is not None and routed["status"] == "executed", message
    execute.assert_awaited_once()


# ── 2. Non-approval does not execute ────────────────────────────────────────


def test_non_approval_keeps_pending_and_does_not_execute():
    _record_pending()
    execute = AsyncMock()

    routed = _route("show me the preview again", execute)

    assert routed is None
    execute.assert_not_awaited()
    pending = router.get_pending_safe_fill(SCOPE)
    assert pending is not None
    assert pending["status"] == "pending_approval"


# ── 3. Submit/apply is never routed through safe fill ───────────────────────


@pytest.mark.parametrize(
    "message",
    ["yes click apply now", "yes submit it", "ok upload my cv",
     "go ahead and press the apply button", "yes, send the application"],
)
def test_high_impact_requests_are_not_routed(message):
    _record_pending()
    execute = AsyncMock()

    routed = _route(message, execute)

    assert routed is None, message
    execute.assert_not_awaited()
    # pending stays — high-impact ask falls to the guarded normal flow
    assert router.get_pending_safe_fill(SCOPE) is not None


# ── 4. No pending action means no route ─────────────────────────────────────


def test_no_pending_action_no_route():
    execute = AsyncMock()
    routed = _route("yes fill it", execute)
    assert routed is None
    execute.assert_not_awaited()


# ── 5. Expired pending action is rejected with exact diagnostic ─────────────


def test_expired_pending_is_rejected_and_cleared():
    entry = _record_pending()
    entry["expires_at"] = time.time() - 1
    execute = AsyncMock()

    routed = _route("yes fill it", execute)

    assert routed is not None
    assert routed["status"] == "expired"
    assert "expired" in routed["message"].lower()
    assert "nothing was filled" in routed["message"].lower()
    execute.assert_not_awaited()
    assert router.get_pending_safe_fill(SCOPE) is None


# ── Approval classifier boundaries ──────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["", "no", "wait", "what does it fill?", "change the email first",
     "yes but also submit", "fill in my password too",
     "x" * 200],
)
def test_not_approval_messages(message):
    assert router.is_approval_message(message) is False


def test_scope_isolation_between_sessions():
    _record_pending()
    execute = AsyncMock()
    routed = asyncio.run(
        router.maybe_route_pending_browser_fill(
            "yes fill it", session_id="some-other-session", execute=execute
        )
    )
    assert routed is None
    execute.assert_not_awaited()


# ── Preview phase records router pending state ──────────────────────────────


def test_preview_phase_records_pending_for_router():
    from src.tool_implementations import do_browser_operator_safe_fill

    router.clear_pending_safe_fill()
    content = json.dumps({"page_url": PAGE_URL, "known_values": KNOWN_VALUES})
    result = asyncio.run(
        do_browser_operator_safe_fill(content, session_id=SESSION)
    )
    assert result.get("pending_confirmation") is True
    pending = router.get_pending_safe_fill(SCOPE)
    assert pending is not None
    assert pending["kind"] == "browser_safe_fill"
    assert pending["page_url"] == PAGE_URL
    assert pending["known_values"] == KNOWN_VALUES
    assert pending["expires_at"] > pending["created_at"]
