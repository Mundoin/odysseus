"""Live-proof router diagnostics — initial preview + approval telemetry.

Stage: odysseus-browser-form-fill-live-proof-router-diagnostics-v1

Proves, independent of model tool emission:
1. initial URL + values + fill-intent message routes a confirmed=false
   preview call backend-side, records pending, logs initial_preview_check hit
2. messages missing URL/values/intent miss with an exact telemetry reason
3. approval routes confirmed=true execution backend-side, clears pending,
   logs approval_execute called=True
4. approval without pending misses with reason=no_pending
5. high-impact approval misses with reason=high_impact_word
6. expired pending misses with reason=expired_pending and exact diagnostic
7. backend-unavailable result is surfaced as a diagnostic, never success
"""
import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock

import pytest

pytestmark = [
    pytest.mark.area_security,
    pytest.mark.sub_browser_form_fill_live_proof_router,
]

from src import form_fill_router as router
from src.browser_operator import browser_action_scope

SESSION = "live-proof-session"
SCOPE = browser_action_scope(session_id=SESSION)
LOGGER = "odysseus.form_fill_router"

SMOKE_PROMPT = """Open this page in the browser, then inspect it:

http://127.0.0.1:8765/odysseus-smoke-form.html

Build a page inventory. Then create a form-fill plan using these values:

first_name: Bujar
last_name: Smoke
email: bujar.smoke@example.com
phone: +49123456789
city: Dortmund
postcode: 44137
cover_letter: Short smoke-test cover letter text.

Fill only safe non-sensitive text fields if supported. Do not fill password fields. Do not upload files. Do not submit or apply. Stop and report what happened."""

EXPECTED_VALUES = {
    "first_name": "Bujar",
    "last_name": "Smoke",
    "email": "bujar.smoke@example.com",
    "phone": "+49123456789",
    "city": "Dortmund",
    "postcode": "44137",
    "cover_letter": "Short smoke-test cover letter text.",
}


@pytest.fixture(autouse=True)
def _clean_pending():
    router.clear_pending_safe_fill()
    yield
    router.clear_pending_safe_fill()


def _preview_route(message, execute):
    return asyncio.run(
        router.maybe_route_initial_preview(
            message, session_id=SESSION, execute=execute, trace="t-test"
        )
    )


def _approval_route(message, execute):
    return asyncio.run(
        router.maybe_route_pending_browser_fill(
            message, session_id=SESSION, execute=execute, trace="t-test"
        )
    )


def _telemetry(caplog, phase):
    return [r.getMessage() for r in caplog.records if f"phase={phase}" in r.getMessage()]


# ── 1. Initial request routes preview before model ──────────────────────────


def test_smoke_prompt_parses_url_values_and_intent():
    parsed = router.parse_fill_request(SMOKE_PROMPT)
    assert parsed["hit"] is True
    assert parsed["page_url"] == "http://127.0.0.1:8765/odysseus-smoke-form.html"
    assert parsed["known_values"] == EXPECTED_VALUES


def test_initial_request_routes_preview_backend_side(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    preview_result = {"pending_confirmation": True, "tool_name": "browser_operator_safe_fill"}
    execute = AsyncMock(return_value=preview_result)

    routed = _preview_route(SMOKE_PROMPT, execute)

    assert routed is not None and routed["status"] == "preview"
    execute.assert_awaited_once()
    args = execute.await_args.args[0]
    assert args["confirmed"] is False
    assert args["page_url"] == "http://127.0.0.1:8765/odysseus-smoke-form.html"
    assert args["known_values"] == EXPECTED_VALUES
    hits = _telemetry(caplog, "initial_preview_check")
    assert any("result=hit" in m for m in hits)
    calls = _telemetry(caplog, "preview_call")
    assert any("confirmed=False" in m and "called=True" in m for m in calls)


def test_initial_preview_records_pending_via_real_tool():
    # Real do_browser_operator_safe_fill: preview phase must record pending
    # for the approval router even with no browser MCP available.
    routed = asyncio.run(
        router.maybe_route_initial_preview(SMOKE_PROMPT, session_id=SESSION, trace="t-real")
    )
    assert routed is not None and routed["status"] == "preview"
    assert routed["result"].get("pending_confirmation") is True
    pending = router.get_pending_safe_fill(SCOPE)
    assert pending is not None
    assert pending["known_values"] == EXPECTED_VALUES


# ── 2. Initial request miss logs reason ──────────────────────────────────────


@pytest.mark.parametrize(
    "message,reason",
    [
        ("fill the form with first_name: Bujar", "no_url"),
        ("open http://127.0.0.1:8765/x.html and fill it", "no_fill_values"),
        ("open http://127.0.0.1:8765/x.html\nfirst_name: Bujar", "no_fill_intent"),
        ("what is the weather today?", "no_url"),
    ],
)
def test_initial_miss_logs_reason(caplog, message, reason):
    caplog.set_level(logging.INFO, logger=LOGGER)
    execute = AsyncMock()
    routed = _preview_route(message, execute)
    assert routed is None
    execute.assert_not_awaited()
    misses = _telemetry(caplog, "initial_preview_check")
    assert any(f"reason={reason}" in m for m in misses), (message, misses)


def test_sensitive_keys_never_parsed_into_fill_values():
    msg = (
        "open http://127.0.0.1:8765/x.html and fill the form\n"
        "first_name: Bujar\npassword: hunter2\napi_key: abc123"
    )
    parsed = router.parse_fill_request(msg)
    assert parsed["hit"] is True
    assert "password" not in parsed["known_values"]
    assert "api_key" not in parsed["known_values"]
    assert parsed["skipped_sensitive_keys"] == 2


# ── 3. Approval routes execution before model ────────────────────────────────


def test_approval_executes_backend_with_telemetry(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    router.record_pending_safe_fill(
        SCOPE, page_url="http://127.0.0.1:8765/x.html", known_values=EXPECTED_VALUES
    )
    execute = AsyncMock(return_value={"output": "Safe fill completed. 7 fields filled, 0 failed, 0 could not be verified. 0 skipped, 0 blocked.", "exit_code": 0})

    routed = _approval_route("yes fill it", execute)

    assert routed is not None and routed["status"] == "executed"
    execute.assert_awaited_once()
    assert execute.await_args.args[0]["confirmed"] is True
    assert router.get_pending_safe_fill(SCOPE) is None
    assert any("result=hit" in m for m in _telemetry(caplog, "approval_check"))
    assert any(
        "confirmed=True" in m and "called=True" in m
        for m in _telemetry(caplog, "approval_execute")
    )
    assert any("status=ok" in m for m in _telemetry(caplog, "backend_result"))
    assert _telemetry(caplog, "pending_cleared")


# ── 4. No pending approval does not execute ──────────────────────────────────


def test_no_pending_miss_telemetry(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    execute = AsyncMock()
    routed = _approval_route("yes fill it", execute)
    assert routed is None
    execute.assert_not_awaited()
    assert any("reason=no_pending" in m for m in _telemetry(caplog, "approval_check"))


# ── 5. High-impact approval does not route ───────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["yes click apply now", "yes submit it", "ok upload the file",
     "approved, send it", "yes, enter my password too"],
)
def test_high_impact_miss_telemetry(caplog, message):
    caplog.set_level(logging.INFO, logger=LOGGER)
    router.record_pending_safe_fill(
        SCOPE, page_url="http://127.0.0.1:8765/x.html", known_values=EXPECTED_VALUES
    )
    execute = AsyncMock()

    routed = _approval_route(message, execute)

    assert routed is None, message
    execute.assert_not_awaited()
    assert router.get_pending_safe_fill(SCOPE) is not None
    assert any(
        "reason=high_impact_word" in m for m in _telemetry(caplog, "approval_check")
    ), message


# ── 6. Expired pending action ────────────────────────────────────────────────


def test_expired_pending_miss_telemetry(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    entry = router.record_pending_safe_fill(
        SCOPE, page_url="http://127.0.0.1:8765/x.html", known_values=EXPECTED_VALUES
    )
    entry["expires_at"] = time.time() - 1
    execute = AsyncMock()

    routed = _approval_route("yes fill it", execute)

    assert routed is not None and routed["status"] == "expired"
    assert "expired" in routed["message"].lower()
    assert "nothing was filled" in routed["message"].lower()
    execute.assert_not_awaited()
    assert router.get_pending_safe_fill(SCOPE) is None
    assert any(
        "reason=expired_pending" in m for m in _telemetry(caplog, "approval_check")
    )


# ── 7. Backend unavailable diagnostic ────────────────────────────────────────


def test_backend_unavailable_is_explicit_diagnostic(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    router.record_pending_safe_fill(
        SCOPE, page_url="http://127.0.0.1:8765/x.html", known_values=EXPECTED_VALUES
    )
    execute = AsyncMock(return_value={
        "error": "Browser fill backend unavailable",
        "diagnostic": {"browser_fill_tool_available": False},
    })

    routed = _approval_route("yes fill it", execute)

    assert routed is not None and routed["status"] == "executed"
    assert routed["result"]["error"] == "Browser fill backend unavailable"
    assert "diagnostic" in routed["result"]
    # success is never implied — no output/succeeded fields present
    assert "output" not in routed["result"]
    assert router.get_pending_safe_fill(SCOPE) is None
    assert any(
        "status=browser_backend_unavailable" in m
        for m in _telemetry(caplog, "backend_result")
    )


# ── Router version visible ───────────────────────────────────────────────────


def test_router_version_log(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    router.log_router_version()
    assert any(
        f"version={router.ROUTER_VERSION}" in r.getMessage() for r in caplog.records
    )
    assert router.ROUTER_VERSION == "live-proof-router-diagnostics-v1"


# ── Live execution bridge (navigate → snapshot → type → verify) ─────────────


PAGE_URL_LIVE = "http://127.0.0.1:8765/odysseus-smoke-form.html"

SNAPSHOT_TEXT = """
- textbox "First name" [ref=e3]
- textbox "Last name" [ref=e5]
- textbox "Email" [ref=e7]
- textbox "Phone" [ref=e9]
- textbox "City" [ref=e11]
- textbox "Postcode" [ref=e13]
- textbox "Cover letter" [ref=e15]
- textbox "Password - should NOT be filled" [ref=e17]
- button "Apply now" [ref=e21]
"""


class _FakeMCP:
    def __init__(self, verify_text=""):
        self.calls = []
        self.verify_text = verify_text

    def get_all_tools(self):
        return [
            {"name": "mcp__builtin_browser__browser_navigate"},
            {"name": "mcp__builtin_browser__browser_snapshot"},
            {"name": "mcp__builtin_browser__browser_type"},
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        if name.endswith("browser_snapshot"):
            snapshots = [c for c in self.calls if c[0].endswith("browser_snapshot")]
            text = SNAPSHOT_TEXT if len(snapshots) == 1 else SNAPSHOT_TEXT + self.verify_text
            return {"content": [{"type": "text", "text": text}]}
        return {"content": [{"type": "text", "text": "ok"}]}


def test_live_fill_navigates_types_safe_fields_and_verifies():
    from src.browser_operator import execute_live_safe_fill

    verify = "\n".join(f"- text: {v}" for v in EXPECTED_VALUES.values())
    mcp = _FakeMCP(verify_text=verify)
    report = asyncio.run(
        execute_live_safe_fill(mcp, PAGE_URL_LIVE, EXPECTED_VALUES, trace="t-live")
    )

    nav_calls = [c for c in mcp.calls if c[0].endswith("browser_navigate")]
    assert nav_calls == [("mcp__builtin_browser__browser_navigate", {"url": PAGE_URL_LIVE})]
    type_calls = [c for c in mcp.calls if c[0].endswith("browser_type")]
    assert len(type_calls) == 7
    typed_refs = {c[1]["ref"] for c in type_calls}
    assert "e17" not in typed_refs  # password textbox never typed
    assert report["succeeded_count"] == 7
    assert report["failed_count"] == 0
    assert any("Password" in b["label"] for b in report["blocked_actions"])
    assert report["exit_code"] == 0


def test_live_fill_navigate_failure_is_explicit():
    from src.browser_operator import execute_live_safe_fill

    class _NavFailMCP(_FakeMCP):
        async def call_tool(self, name, args):
            if name.endswith("browser_navigate"):
                return {"error": "net::ERR_CONNECTION_REFUSED", "exit_code": 1}
            return await super().call_tool(name, args)

    report = asyncio.run(
        execute_live_safe_fill(_NavFailMCP(), PAGE_URL_LIVE, EXPECTED_VALUES)
    )
    assert "navigation" in report["error"].lower()
    assert report["exit_code"] == 1


def test_live_fill_unverified_values_reported_unknown():
    from src.browser_operator import execute_live_safe_fill

    mcp = _FakeMCP(verify_text="")  # post-fill snapshot shows nothing
    report = asyncio.run(
        execute_live_safe_fill(mcp, PAGE_URL_LIVE, EXPECTED_VALUES)
    )
    assert report["succeeded_count"] == 0
    assert report["unknown_count"] == 7


def test_live_fill_handles_mcp_manager_stdout_shape():
    # The real MCP manager returns {"stdout","stderr","exit_code"} dicts.
    from src.browser_operator import execute_live_safe_fill

    class _StdoutMCP(_FakeMCP):
        async def call_tool(self, name, args):
            self.calls.append((name, dict(args)))
            if name.endswith("browser_snapshot"):
                snaps = [c for c in self.calls if c[0].endswith("browser_snapshot")]
                text = SNAPSHOT_TEXT if len(snaps) == 1 else SNAPSHOT_TEXT + self.verify_text
                return {"stdout": text, "stderr": "", "exit_code": 0}
            return {"stdout": "ok", "stderr": "", "exit_code": 0}

    verify = "\n".join(f"- text: {v}" for v in EXPECTED_VALUES.values())
    mcp = _StdoutMCP(verify_text=verify)
    report = asyncio.run(execute_live_safe_fill(mcp, PAGE_URL_LIVE, EXPECTED_VALUES))
    assert report["succeeded_count"] == 7
    assert report["exit_code"] == 0


def test_live_fill_nonzero_exit_code_navigate_is_failure():
    from src.browser_operator import execute_live_safe_fill

    class _ExitCodeFailMCP(_FakeMCP):
        async def call_tool(self, name, args):
            if name.endswith("browser_navigate"):
                return {"stdout": "", "stderr": "net::ERR_CONNECTION_REFUSED", "exit_code": 1}
            return await super().call_tool(name, args)

    report = asyncio.run(
        execute_live_safe_fill(_ExitCodeFailMCP(), PAGE_URL_LIVE, EXPECTED_VALUES)
    )
    assert report["exit_code"] == 1
    assert "ERR_CONNECTION_REFUSED" in report["error"]
