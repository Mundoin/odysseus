"""Deterministic approval router for pending browser safe-fill actions.

Stage: odysseus-browser-form-fill-autopilot-router-v1

Problem this solves: after `browser_operator_safe_fill` returns a
pending_confirmation preview, execution used to depend on the model emitting
the confirmed tool call. Several models (Mimo family) narrate "I will call
browser_operator_safe_fill" instead of calling it, stalling the loop.

Fix: the backend owns the execution switch. When a pending safe-fill request
exists for the current chat scope and the user's next message is an
approval, the agent loop calls `maybe_route_pending_browser_fill()` BEFORE
any model tool choice and executes `browser_operator_safe_fill` with
``confirmed=true`` directly.

Scope limits (hard):
- Routes safe text-field fill ONLY. Password / upload / submit / apply /
  payment / send / delete intents are never routed; those words in the
  approval message disqualify routing entirely.
- Pending state is in-memory and ephemeral (TTL), never persisted.
"""

import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from src.browser_operator import browser_action_scope

logger = logging.getLogger("odysseus.form_fill_router")

# How long an unapproved preview stays actionable.
PENDING_SAFE_FILL_TTL_SECONDS = 15 * 60

# scope -> pending safe-fill request (raw args needed for backend re-execution)
_PENDING_SAFE_FILL: Dict[str, Dict[str, Any]] = {}

# Short messages only — a paragraph is instructions, not an approval.
_MAX_APPROVAL_LENGTH = 80

_APPROVAL_RE = re.compile(
    r"^(?:yes|yep|yeah|y|ok|okay|sure|approved?|confirm(?:ed)?|proceed|go|"
    r"go ahead|do it|fill(?: it| them| the form)?(?: in)?|run it|execute|"
    r"please do|sounds good|looks good|lgtm)"
    r"(?:[\s,]+(?:please|yes|ok|okay|sure|go ahead|do it|proceed|"
    r"fill(?: it| them| the form)?(?: in)?|fill|it|in|them|the form|now|then))*$"
)

# Any of these in the message means the user is asking for MORE than the
# approved safe fill — never route, let the normal guarded flow handle it.
_HIGH_IMPACT_RE = re.compile(
    r"(?i)\b(submit|apply|click|press|button|upload|attach|file|cv|resume|"
    r"send|e-?mail|delete|remove|cancel|pay|payment|checkout|buy|purchase|"
    r"order|password|login|log in|sign in|sign up|register|evaluate|script)\b"
)


def record_pending_safe_fill(
    scope: str,
    *,
    page_url: str,
    known_values: Dict[str, Any],
    form_fill_plan: Optional[Dict[str, Any]] = None,
    batch_size: int = 3,
    ttl_seconds: float = PENDING_SAFE_FILL_TTL_SECONDS,
) -> Dict[str, Any]:
    """Remember the full safe-fill request so the backend can execute it on
    approval without any model involvement. Raw values stay in process
    memory only and are dropped on consume/expiry."""
    now = time.time()
    entry = {
        "kind": "browser_safe_fill",
        "page_url": page_url,
        "known_values": dict(known_values),
        "form_fill_plan": form_fill_plan,
        "batch_size": batch_size,
        "created_at": now,
        "expires_at": now + ttl_seconds,
        "status": "pending_approval",
    }
    _PENDING_SAFE_FILL[scope] = entry
    logger.info(
        "[fill-router] recorded pending safe fill scope=%s url=%s fields=%d",
        scope, page_url, len(known_values),
    )
    return entry


def get_pending_safe_fill(scope: str) -> Optional[Dict[str, Any]]:
    return _PENDING_SAFE_FILL.get(scope)


def clear_pending_safe_fill(scope: Optional[str] = None) -> None:
    if scope is None:
        _PENDING_SAFE_FILL.clear()
    else:
        _PENDING_SAFE_FILL.pop(scope, None)


def _normalise(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[!.?]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_approval_message(text: str) -> bool:
    """True only for short, pure approval messages with no high-impact ask."""
    raw = (text or "").strip()
    if not raw or len(raw) > _MAX_APPROVAL_LENGTH:
        return False
    if _HIGH_IMPACT_RE.search(raw):
        return False
    return bool(_APPROVAL_RE.match(_normalise(raw)))


async def _default_execute(args: Dict[str, Any]) -> Dict[str, Any]:
    from src.tool_implementations import do_browser_operator_safe_fill

    owner = args.pop("_owner", None)
    session_id = args.pop("_session_id", None)
    return await do_browser_operator_safe_fill(
        json.dumps(args), owner=owner, session_id=session_id
    )


async def maybe_route_pending_browser_fill(
    user_message: str,
    *,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
    execute: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
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
        return None
    if not is_approval_message(user_message):
        return None

    if time.time() > float(pending.get("expires_at", 0)):
        clear_pending_safe_fill(scope)
        logger.info("[fill-router] pending safe fill expired scope=%s", scope)
        return {
            "status": "expired",
            "scope": scope,
            "message": (
                "The pending safe form fill approval has expired "
                f"(older than {int(PENDING_SAFE_FILL_TTL_SECONDS // 60)} minutes). "
                "Nothing was filled. Ask for a fresh preview to approve again."
            ),
        }

    args: Dict[str, Any] = {
        "page_url": pending["page_url"],
        "known_values": pending["known_values"],
        "confirmed": True,
        "batch_size": pending.get("batch_size", 3),
        "_owner": owner,
        "_session_id": session_id,
    }
    if pending.get("form_fill_plan"):
        args["form_fill_plan"] = pending["form_fill_plan"]

    runner = execute or _default_execute
    logger.info(
        "[fill-router] approval detected; backend executing safe fill scope=%s url=%s",
        scope, pending["page_url"],
    )
    try:
        result = await runner(args)
    finally:
        # One approval == one execution attempt. Never replayable.
        clear_pending_safe_fill(scope)

    return {
        "status": "executed",
        "scope": scope,
        "page_url": pending["page_url"],
        "result": result,
    }
