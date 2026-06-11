"""Deterministic routers for browser safe-fill: direct fill + optional preview.

Stage: odysseus-browser-form-fill-live-proof-router-diagnostics-v1
(supersedes odysseus-browser-form-fill-autopilot-router-v1)

Two model-independent routing points, both running BEFORE model tool choice:

1. Direct fill-only router — a user message carrying a URL and normal
   text-field fill intent triggers backend-owned `browser_operator_safe_fill`
   with ``direct_fill_only=true``. No approval loop is required for this narrow
   action class.

2. Optional preview router — if the user explicitly asks to preview/review
   before filling, the old pending approval path remains available.

Every decision emits structured telemetry:
    [form-fill-router] trace=<id> phase=<phase> key=value ...
so live server logs prove exactly which layer fired or missed.

Scope limits (hard):
- Safe text-field fill ONLY. Password / upload / submit / apply / payment /
  send / delete intents are never routed; high-impact words in an approval
  disqualify routing entirely (reason=high_impact_word).
- Pending state is in-memory and ephemeral (TTL), never persisted.
- Telemetry is redacted: field counts and key names only, never raw values.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from src.browser_operator import browser_action_scope

logger = logging.getLogger("odysseus.form_fill_router")

ROUTER_VERSION = "live-proof-router-diagnostics-v1"

# How long an unapproved preview stays actionable.
PENDING_SAFE_FILL_TTL_SECONDS = 15 * 60

# scope -> pending safe-fill request (raw args needed for backend re-execution)
_PENDING_SAFE_FILL: Dict[str, Dict[str, Any]] = {}

# scope -> redacted record of the last completed safe fill. Lets a repeated
# approval report "already completed" instead of re-running or confusing the
# model, and keeps browser tools pinned for the reporting turns.
_COMPLETED_SAFE_FILL: Dict[str, Dict[str, Any]] = {}
COMPLETED_SAFE_FILL_TTL_SECONDS = 15 * 60

# Raw fill/type tools the model must not improvise with while a safe-fill
# action is pending — the canonical wrapper owns execution.
_RAW_FILL_TOOL_BARE_NAMES = frozenset({
    "browser_fill_form", "browser_fill", "browser_type", "browser_select_option",
})

# Short messages only — a paragraph is instructions, not an approval.
_MAX_APPROVAL_LENGTH = 80

_APPROVAL_RE = re.compile(
    r"^(?:yes|yep|yeah|y|ok|okay|sure|approved?|confirm(?:ed)?|proceed|go|"
    r"go ahead|do it|continue|fill(?: it| them| the form)?(?: in)?|run it|execute|"
    r"please do|sounds good|looks good|lgtm)"
    r"(?:[\s,]+(?:please|yes|ok|okay|sure|go ahead|do it|proceed|continue|"
    r"approved?|fill(?: it| them| the form)?(?: in)?|fill|it|in|them|the form|now|then))*$"
)

# Natural approval sentences that don't fit the strict token chain above:
# "Yes Approved.", "Yes, approve and execute fill", "Yes I approve, you can
# proceed, go!". An unambiguous approval verb/phrase anywhere in a short,
# high-impact-free message counts. Bare "yes"/"ok" stay strict-match only so
# "yes, but ..." prose can't route by accident.
_APPROVAL_INTENT_RE = re.compile(
    r"\b(?:approved?|i approve|we approve|go ahead|you can proceed|proceed|"
    r"do it|run it|execute(?: the)?(?: safe)? fill|fill (?:it|now|them))\b"
)

# Any of these in the message means the user is asking for MORE than the
# approved safe fill — never route, let the normal guarded flow handle it.
_HIGH_IMPACT_RE = re.compile(
    r"(?i)\b(submit|apply|click|press|button|upload|attach|file|cv|resume|"
    r"send|e-?mail|delete|remove|cancel|pay|payment|checkout|buy|purchase|"
    r"order|password|login|log in|sign in|sign up|register|evaluate|script)\b"
)

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_FILL_INTENT_RE = re.compile(
    r"(?i)\b(fill|form[- ]?fill|safe fields|provided values|enter (?:these|the) values)\b"
)
_EXPLICIT_PREVIEW_RE = re.compile(
    r"(?i)\b(preview|review first|show (?:me )?(?:the )?plan|ask (?:me )?before|approve first|approval first)\b"
)
_TEST_DATA_RE = re.compile(
    r"(?i)\b(simple test data|test data|dummy data|sample data|normal visible form fields|normal fields)\b"
)
_KV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_ ]{0,40}?)\s*:\s*(\S.*)$")

# Keys never accepted as fill values, even if the user provides them inline.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)\b(password|passwd|pass|token|secret|api[_ ]?key|cvv|cvc|card|iban|"
    r"ssn|tax|health|pin)\b"
)
# key:value parsing must not swallow prose lines ("Open this page in the
# browser, then inspect it:") — keys are short identifiers, max 3 words.
_MAX_KEY_WORDS = 3

DEFAULT_NORMAL_FIELD_TEST_VALUES: Dict[str, str] = {
    "first_name": "TEST123",
    "last_name": "VISIBLE",
    "email": "test123@example.com",
    "phone": "+49123456789",
    "city": "Dortmund",
    "postcode": "44137",
    "cover_letter": "Visible fill proof test cover letter.",
}


def new_trace_id() -> str:
    return uuid.uuid4().hex[:8]


def _tlog(trace: Optional[str], phase: str, **fields: Any) -> None:
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("[form-fill-router] trace=%s phase=%s %s", trace or "-", phase, extra)


def log_router_version() -> None:
    logger.info("[form-fill-router] version=%s", ROUTER_VERSION)


def record_pending_safe_fill(
    scope: str,
    *,
    page_url: str,
    known_values: Dict[str, Any],
    form_fill_plan: Optional[Dict[str, Any]] = None,
    batch_size: int = 3,
    visible_mode: bool = True,
    visible_fill_delay_ms: int = 550,
    keep_browser_open: bool = True,
    ttl_seconds: float = PENDING_SAFE_FILL_TTL_SECONDS,
    trace: Optional[str] = None,
) -> Dict[str, Any]:
    """Remember the full safe-fill request so the backend can execute it on
    approval without any model involvement. Raw values stay in process
    memory only and are dropped on consume/expiry."""
    now = time.time()
    entry = {
        "kind": "browser_safe_fill",
        "pending_id": f"safe-fill:{uuid.uuid4().hex[:12]}",
        "page_url": page_url,
        "known_values": dict(known_values),
        "form_fill_plan": form_fill_plan,
        "batch_size": batch_size,
        "visible_mode": visible_mode,
        "visible_fill_delay_ms": visible_fill_delay_ms,
        "keep_browser_open": keep_browser_open,
        "created_at": now,
        "expires_at": now + ttl_seconds,
        "status": "pending_approval",
    }
    _PENDING_SAFE_FILL[scope] = entry
    # A fresh preview supersedes any previous completed record for this chat.
    _COMPLETED_SAFE_FILL.pop(scope, None)
    _tlog(
        trace, "pending_recorded",
        pending_id=entry["pending_id"], scope=scope,
        values_count=len(known_values), visible_mode=visible_mode,
        delay_ms=visible_fill_delay_ms, ttl_seconds=int(ttl_seconds),
    )
    return entry


def get_pending_safe_fill(scope: str) -> Optional[Dict[str, Any]]:
    return _PENDING_SAFE_FILL.get(scope)


def has_pending_safe_fill(
    session_id: Optional[str] = None, owner: Optional[str] = None
) -> bool:
    """True when this chat scope has an unexpired pending safe fill.

    Approval turns ("approved") carry no browser keywords, so intent
    detection marks them low-signal and the tool set collapses to
    always-available tools only. The agent loop uses this check to force
    browser tool relevance while an approval is still pending."""
    scope = browser_action_scope(session_id=session_id, owner=owner)
    entry = _PENDING_SAFE_FILL.get(scope)
    if not entry or entry.get("kind") != "browser_safe_fill":
        return False
    return time.time() <= float(entry.get("expires_at", 0))


def has_recent_fill_activity(
    session_id: Optional[str] = None, owner: Optional[str] = None
) -> bool:
    """True while this chat has a pending OR recently completed safe fill.

    Used by the agent loop to keep browser tools pinned across the whole
    flow — pending, executing and reporting turns — so the tool schema set
    can never collapse mid-conversation."""
    if has_pending_safe_fill(session_id=session_id, owner=owner):
        return True
    scope = browser_action_scope(session_id=session_id, owner=owner)
    completed = _COMPLETED_SAFE_FILL.get(scope)
    return bool(completed and time.time() <= float(completed.get("expires_at", 0)))


def _record_completed_safe_fill(
    scope: str,
    pending: Dict[str, Any],
    result: Any,
    trace: Optional[str] = None,
) -> None:
    """Remember (redacted) that this scope's fill was executed, so repeated
    approvals report 'already completed' instead of re-running."""
    result_dict = result if isinstance(result, dict) else {}
    now = time.time()
    record = {
        "pending_id": pending.get("pending_id"),
        "page_url": pending.get("page_url"),
        "completed_at": now,
        "expires_at": now + COMPLETED_SAFE_FILL_TTL_SECONDS,
        "lifecycle": result_dict.get("lifecycle"),
        "succeeded_count": result_dict.get("succeeded_count"),
        "output": _result_summary(result_dict),
    }
    _COMPLETED_SAFE_FILL[scope] = record
    _tlog(
        trace, "completed_recorded",
        pending_id=record["pending_id"], scope=scope,
        lifecycle=record["lifecycle"], succeeded=record["succeeded_count"],
    )


def intercept_raw_fill_tool(
    tool_name: str,
    *,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
    trace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Runtime enforcement: while a safe-fill action is pending for this
    chat, the model may not improvise raw browser fill/type tool calls —
    the canonical wrapper owns execution. Returns a short-circuit result
    dict, or None to allow the call."""
    bare = str(tool_name or "").rsplit("__", 1)[-1]
    if bare not in _RAW_FILL_TOOL_BARE_NAMES:
        return None
    scope = browser_action_scope(session_id=session_id, owner=owner)
    pending = _PENDING_SAFE_FILL.get(scope)
    if not pending or pending.get("kind") != "browser_safe_fill":
        return None
    if time.time() > float(pending.get("expires_at", 0)):
        return None
    status = pending.get("status", "pending_approval")
    _tlog(
        trace, "raw_fill_intercepted",
        tool=tool_name, scope=scope,
        pending_id=pending.get("pending_id"), pending_status=status,
    )
    if status == "executing":
        message = (
            "The approved browser form fill is already executing on the backend. "
            "Do not call browser tools. Wait for the backend result and report it."
        )
    else:
        message = (
            "A pending browser safe form fill exists for this chat "
            f"(id {pending.get('pending_id')}). Do not improvise raw browser "
            "fill/type tool calls. When the user approves, Odysseus executes the "
            "pending action automatically on the backend; until then, show the "
            "preview and wait. The only valid form-fill tool is "
            "browser_operator_safe_fill."
        )
    return {
        "error": message,
        "intercepted": "pending_safe_fill",
        "pending_id": pending.get("pending_id"),
        "exit_code": 1,
    }


def clear_pending_safe_fill(scope: Optional[str] = None, trace: Optional[str] = None) -> None:
    if scope is None:
        _PENDING_SAFE_FILL.clear()
        _COMPLETED_SAFE_FILL.clear()
        return
    entry = _PENDING_SAFE_FILL.pop(scope, None)
    if entry:
        _tlog(trace, "pending_cleared", pending_id=entry.get("pending_id"), scope=scope)


def _normalise(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[!.?]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def approval_check(text: str) -> Tuple[bool, str]:
    """Classify a message as approval. Returns (hit, reason)."""
    raw = (text or "").strip()
    if not raw:
        return False, "empty_message"
    if len(raw) > _MAX_APPROVAL_LENGTH:
        return False, "too_long"
    if _HIGH_IMPACT_RE.search(raw):
        return False, "high_impact_word"
    norm = _normalise(raw)
    if _APPROVAL_RE.match(norm) or _APPROVAL_INTENT_RE.search(norm):
        return True, "approval"
    return False, "not_approval"


def is_approval_message(text: str) -> bool:
    """True only for short, pure approval messages with no high-impact ask."""
    return approval_check(text)[0]


def parse_fill_request(message: str) -> Dict[str, Any]:
    """Extract URL + key:value fill values + fill intent from a user message.

    Returns {"hit": True, "page_url": ..., "known_values": {...}} or
    {"hit": False, "reason": no_url|no_fill_values|no_fill_intent}.
    """
    text = message or ""
    url_match = _URL_RE.search(text)
    if not url_match:
        return {"hit": False, "reason": "no_url"}
    page_url = url_match.group(0).rstrip(".,;")

    if not _FILL_INTENT_RE.search(text):
        return {"hit": False, "reason": "no_fill_intent"}

    known_values: Dict[str, str] = {}
    skipped_sensitive = 0
    for line in text.splitlines():
        if "://" in line:
            continue
        m = _KV_LINE_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if len(key.split()) > _MAX_KEY_WORDS:
            continue
        if _SENSITIVE_KEY_RE.search(key):
            skipped_sensitive += 1
            continue
        known_values[key.lower().replace(" ", "_")] = value

    if not known_values and _TEST_DATA_RE.search(text):
        known_values = dict(DEFAULT_NORMAL_FIELD_TEST_VALUES)

    if not known_values:
        return {"hit": False, "reason": "no_fill_values"}

    return {
        "hit": True,
        "page_url": page_url,
        "known_values": known_values,
        "skipped_sensitive_keys": skipped_sensitive,
        "explicit_preview": bool(_EXPLICIT_PREVIEW_RE.search(text)),
    }


async def _default_execute(args: Dict[str, Any]) -> Dict[str, Any]:
    from src.tool_implementations import do_browser_operator_safe_fill

    owner = args.pop("_owner", None)
    session_id = args.pop("_session_id", None)
    args.pop("_trace", None)
    return await do_browser_operator_safe_fill(
        json.dumps(args), owner=owner, session_id=session_id
    )


def _result_status(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return "non_dict_result"
    if result.get("error"):
        if "unavailable" in str(result.get("error", "")).lower():
            return "browser_backend_unavailable"
        return "error"
    if result.get("pending_confirmation"):
        return "pending_confirmation"
    return "ok"


def _result_summary(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return str(type(result).__name__)
    text = result.get("output") or result.get("error") or result.get("message") or ""
    return str(text)[:160].replace("\n", " ")


async def maybe_route_initial_preview(
    user_message: str,
    *,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
    execute: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    trace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Deterministic initial direct-fill/preview router. Runs before model choice.

    Normal fill-only requests execute immediately. If the user explicitly asks
    for a preview/review/approval first, the old pending preview path is used.

    Returns None (no route), {"status": "executed", ...}, or
    {"status": "preview", "result": <preview>}.
    """
    parsed = parse_fill_request(user_message)
    if not parsed.get("hit"):
        _tlog(trace, "initial_preview_check", result="miss", reason=parsed.get("reason"))
        return None

    scope = browser_action_scope(session_id=session_id, owner=owner)
    _tlog(
        trace, "initial_preview_check",
        result="hit", scope=scope, url_present=True,
        values_count=len(parsed["known_values"]), fill_intent=True,
    )
    _tlog(
        trace, "initial_preview_parse",
        url_present=True, values_count=len(parsed["known_values"]),
        fill_intent=True, skipped_sensitive_keys=parsed.get("skipped_sensitive_keys", 0),
    )

    args: Dict[str, Any] = {
        "page_url": parsed["page_url"],
        "known_values": parsed["known_values"],
        "confirmed": bool(not parsed.get("explicit_preview")),
        "direct_fill_only": bool(not parsed.get("explicit_preview")),
        "fill_only_no_approval": bool(not parsed.get("explicit_preview")),
        "visible_mode": True,
        "visible_fill_delay_ms": 550,
        "keep_browser_open": True,
        "_owner": owner,
        "_session_id": session_id,
        "_trace": trace,
    }
    runner = execute or _default_execute
    if parsed.get("explicit_preview"):
        _tlog(trace, "preview_call", tool="browser_operator_safe_fill", confirmed=False, called=True)
    else:
        _tlog(trace, "direct_fill_call", tool="browser_operator_safe_fill", confirmed=True, called=True)
    result = await runner(args)
    status = _result_status(result)
    _tlog(trace, "backend_result", status=status, summary=_result_summary(result))

    if not parsed.get("explicit_preview"):
        return {
            "status": "executed",
            "scope": scope,
            "page_url": parsed["page_url"],
            "values_count": len(parsed["known_values"]),
            "result": result,
            "trace": trace,
            "mode": "direct_fill_only",
        }

    return {
        "status": "preview",
        "scope": scope,
        "page_url": parsed["page_url"],
        "values_count": len(parsed["known_values"]),
        "result": result,
        "trace": trace,
    }


async def maybe_route_pending_browser_fill(
    user_message: str,
    *,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
    execute: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    trace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Deterministic approval router. Runs BEFORE model tool choice.

    Returns:
      None                                  — no route; normal agent flow.
      {"status": "executed", "result": ...} — backend executed the approved fill.
      {"status": "expired", "message": ...} — pending fill expired; cleared.
    """
    scope = browser_action_scope(session_id=session_id, owner=owner)
    pending = _PENDING_SAFE_FILL.get(scope)
    if not pending or pending.get("kind") != "browser_safe_fill":
        # Repeated approval after the fill already ran: report the existing
        # result instead of confusing the model into a second approval loop.
        completed = _COMPLETED_SAFE_FILL.get(scope)
        if completed and time.time() <= float(completed.get("expires_at", 0)):
            hit, _ = approval_check(user_message)
            if hit:
                _tlog(
                    trace, "approval_check",
                    result="hit", reason="already_completed", scope=scope,
                    pending_id=completed.get("pending_id"),
                )
                return {
                    "status": "already_completed",
                    "scope": scope,
                    "page_url": completed.get("page_url"),
                    "message": (
                        "That browser form fill was already executed. Result: "
                        f"{completed.get('output') or 'reported earlier in this chat'}. "
                        "Nothing was re-run. Ask for a fresh preview to fill again."
                    ),
                    "completed": dict(completed),
                }
        # other_pending_scopes > 0 with a miss here means the preview was
        # recorded under a different scope (session/owner mismatch between
        # turns) — the classic "approved but nothing happened" diagnostic.
        _tlog(
            trace, "approval_check",
            result="miss", reason="no_pending", scope=scope,
            other_pending_scopes=len(_PENDING_SAFE_FILL),
        )
        return None

    hit, reason = approval_check(user_message)
    if not hit:
        _tlog(
            trace, "approval_check",
            result="miss", reason=reason, scope=scope,
            pending_id=pending.get("pending_id"),
        )
        return None

    if time.time() > float(pending.get("expires_at", 0)):
        _tlog(
            trace, "approval_check",
            result="miss", reason="expired_pending", scope=scope,
            pending_id=pending.get("pending_id"),
        )
        clear_pending_safe_fill(scope, trace=trace)
        return {
            "status": "expired",
            "scope": scope,
            "message": (
                "The pending safe form fill approval has expired "
                f"(older than {int(PENDING_SAFE_FILL_TTL_SECONDS // 60)} minutes). "
                "Nothing was filled. Ask for a fresh preview to approve again."
            ),
        }

    if pending.get("status") == "executing":
        _tlog(
            trace, "approval_check",
            result="hit", reason="already_executing", scope=scope,
            pending_id=pending.get("pending_id"),
        )
        return {
            "status": "already_executing",
            "scope": scope,
            "page_url": pending.get("page_url"),
            "message": (
                "The approved browser form fill is already executing. "
                "No second run was started. Wait for its result."
            ),
        }

    _tlog(
        trace, "approval_check",
        result="hit", reason="approval", scope=scope,
        pending_id=pending.get("pending_id"),
    )
    pending["status"] = "executing"

    args: Dict[str, Any] = {
        "page_url": pending["page_url"],
        "known_values": pending["known_values"],
        "confirmed": True,
        "batch_size": pending.get("batch_size", 3),
        "visible_mode": pending.get("visible_mode", True),
        "visible_fill_delay_ms": pending.get("visible_fill_delay_ms", 550),
        "keep_browser_open": pending.get("keep_browser_open", True),
        "_owner": owner,
        "_session_id": session_id,
    }
    if pending.get("form_fill_plan"):
        args["form_fill_plan"] = pending["form_fill_plan"]

    runner = execute or _default_execute
    _tlog(trace, "approval_execute", tool="browser_operator_safe_fill", confirmed=True, called=True)
    try:
        result = await runner(args)
    finally:
        # One approval == one execution attempt. Never replayable.
        clear_pending_safe_fill(scope, trace=trace)

    _record_completed_safe_fill(scope, pending, result, trace=trace)
    _tlog(trace, "backend_result", status=_result_status(result), summary=_result_summary(result))

    return {
        "status": "executed",
        "scope": scope,
        "page_url": pending["page_url"],
        "result": result,
    }
