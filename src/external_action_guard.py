"""
Central guardrail for external-action tools (api_call, app_api, etc.).

Pattern mirrors the email send guardrail: first call without confirmed returns
a pending_confirmation preview; re-call with confirmed=true executes.

Action classes
--------------
safe_read               GET / read-only — no gate
local_prepare           local state change with no external side-effect — no gate
external_write          mutates external or server-side state (POST/PUT/PATCH/DELETE)
high_impact_external_write  financial, legal, destructive, or security-sensitive write
"""
from __future__ import annotations
from typing import Any
from urllib.parse import urlparse

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Substrings in path/action/target that escalate to high-impact.
_HIGH_IMPACT_KEYWORDS = (
    "buy", "order", "pay", "payment", "purchase", "checkout", "cart",
    "cancel", "refund", "chargeback", "dispute",
    "delete", "destroy", "purge", "wipe",
    "submit", "publish",
    "account", "password", "credential", "secret",
    "security", "2fa", "mfa",
    "tax", "invoice", "billing", "contract",
    "upload", "transfer", "wire",
)


def classify(method: str, target: str) -> str:
    """Return the action class for a (method, target) pair."""
    if method.upper() not in _WRITE_METHODS:
        return "safe_read"
    if any(kw in (target or "").lower() for kw in _HIGH_IMPACT_KEYWORDS):
        return "high_impact_external_write"
    return "external_write"


_MAX_ARG_PREVIEW_CHARS = 300


def _extract_domain(*candidates: Any) -> str | None:
    """First http(s) candidate's netloc, or None."""
    for c in candidates:
        if isinstance(c, str) and c.startswith(("http://", "https://")):
            netloc = urlparse(c).netloc
            if netloc:
                return netloc
    return None


def _matched_high_impact_keywords(text: str) -> list[str]:
    low = (text or "").lower()
    return [kw for kw in _HIGH_IMPACT_KEYWORDS if kw in low]


def _compact_args(value: Any, depth: int = 0) -> Any:
    """Concise copy of arguments for operator display: truncate long strings,
    cap list length, bound nesting depth. Original body is never mutated."""
    if isinstance(value, str):
        if len(value) <= _MAX_ARG_PREVIEW_CHARS:
            return value
        return value[:_MAX_ARG_PREVIEW_CHARS] + f"… [{len(value)} chars total]"
    if isinstance(value, dict) and depth < 4:
        return {str(k): _compact_args(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)) and depth < 4:
        items = [_compact_args(v, depth + 1) for v in list(value)[:10]]
        if len(value) > 10:
            items.append(f"… {len(value) - 10} more items")
        return items
    return value


def build_preview(
    *,
    tool: str,
    method: str,
    target: str,
    body: Any = None,
    integration: str | None = None,
    action_class: str,
    action_name: str | None = None,
    url: str | None = None,
    summary: str | None = None,
    high_impact_reason: str | None = None,
) -> dict:
    high = action_class == "high_impact_external_write"
    action = action_name or method.upper()
    domain = _extract_domain(url, target)
    risk = (
        "HIGH IMPACT: This action may be financially, legally, or security-sensitive "
        "and cannot be automatically reversed."
        if high
        else "This action mutates external or server-side state and cannot be undone automatically."
    )
    if summary is None:
        via = f" via the '{integration}' integration" if integration else ""
        summary = (
            f"Odysseus is about to send a {method.upper()} request to {target}{via} "
            f"using tool {tool}. This may change external or server-side state. "
            "Approval is required before execution."
        )
    consequences = (
        "If approved, Odysseus will execute this action immediately. It may move money, "
        "alter legal or account state, delete data, or send externally visible content, "
        "and cannot be automatically reversed."
        if high
        else "If approved, Odysseus will execute this action immediately. It will change "
        "external or server-side state and cannot be undone automatically."
    )
    approval_instruction = (
        "Show this preview to the user and ask for explicit approval before proceeding. "
        "Re-call with confirmed=true to execute."
    )
    preview: dict[str, Any] = {
        # primary signal (legacy consumers key on pending_confirmation)
        "pending_confirmation": True,
        "confirmation_required": True,
        # what / where
        "tool": tool,
        "tool_name": tool,
        "action_name": action,
        "action_type": action_class,
        "action_category": action_class,
        "risk_level": "high" if high else "normal",
        "method": method.upper(),
        "target": target,
        # operator-facing narrative
        "summary": summary,
        "consequences": consequences,
        "risk": risk,
        "instruction": approval_instruction,
        "approval_instruction": approval_instruction,
    }
    if domain:
        preview["target_domain"] = domain
    if url:
        preview["url"] = url
    if integration:
        preview["integration"] = integration
    if body is not None:
        preview["body_preview"] = body
        preview["arguments_preview"] = _compact_args(body)
    if high:
        if not high_impact_reason:
            kws = _matched_high_impact_keywords(target)
            high_impact_reason = (
                f"target matches high-impact keyword(s): {', '.join(kws)}"
                if kws
                else "action is classified as financially, legally, destructive, or security-sensitive"
            )
        preview["high_impact"] = True
        preview["high_impact_reason"] = high_impact_reason
        preview["final_checklist"] = {
            "target": target,
            "method": method.upper(),
            "service": integration or "unknown",
            "body": body,
            "financial_impact": "unknown — review before confirming",
            "legal_consequence": "unknown — review before confirming",
        }
        preview["final_review_checklist"] = [
            f"Target is correct: {target}",
            f"Action is intended: {action} ({action_class})",
            "Data being sent has been reviewed (see arguments_preview)",
            "Financial, legal, or destructive impact is understood and acceptable",
            "The user explicitly requested this action",
        ]
    return preview


def guard(
    *,
    tool: str,
    method: str,
    target: str,
    confirmed: bool,
    body: Any = None,
    integration: str | None = None,
) -> dict | None:
    """
    Return a pending_confirmation dict when the action needs user confirmation,
    or None when execution should proceed.
    """
    action_class = classify(method, target)
    if action_class == "safe_read":
        return None
    if confirmed:
        return None
    return build_preview(
        tool=tool,
        method=method,
        target=target,
        body=body,
        integration=integration,
        action_class=action_class,
    )


# ---------------------------------------------------------------------------
# MCP tool guardrail
# ---------------------------------------------------------------------------

_SAFE_MCP_TOOLS = frozenset({
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_screenshot",
    "browser_navigate",
    "browser_navigate_back",
    "browser_wait_for",
    "browser_console_messages",
    "browser_network_requests",
    "browser_tabs",
    "browser_resize",
    "browser_hover",
    "browser_close",
})

# Local state changes with no external side-effect — no gate needed.
_LOCAL_PREPARE_MCP_TOOLS = frozenset({
    "browser_type",
    "browser_fill",
    "browser_select_option",
    "browser_drag",
    "browser_drop",
})

_ALWAYS_HIGH_IMPACT_MCP_TOOLS = frozenset({
    "browser_file_upload",
    "browser_run_code_unsafe",
    "browser_evaluate",
})

_CLICK_HIGH_IMPACT_KEYWORDS = (
    "submit", "send", "pay", "buy", "order", "purchase", "confirm",
    "checkout", "cancel", "refund", "return", "delete", "remove", "apply",
    "activate", "subscribe", "upload", "proceed", "complete",
    "place order",
)


def _bare_mcp_tool_name(tool: str) -> str:
    """mcp__playwright__browser_click → browser_click"""
    if "__" in tool:
        return tool.rsplit("__", 1)[-1]
    return tool


def classify_mcp_tool(tool: str, args: dict) -> str:
    """Return action class for an MCP tool call."""
    name = _bare_mcp_tool_name(tool)

    if name in _SAFE_MCP_TOOLS:
        return "safe_read"
    if name in _LOCAL_PREPARE_MCP_TOOLS:
        return "local_prepare"
    if name in _ALWAYS_HIGH_IMPACT_MCP_TOOLS:
        return "high_impact_external_write"

    if name == "browser_click":
        element = (
            args.get("element") or args.get("ref") or args.get("selector") or ""
        ).lower()
        if any(kw in element for kw in _CLICK_HIGH_IMPACT_KEYWORDS):
            return "high_impact_external_write"
        return "external_write"

    if name == "browser_press_key":
        key = (args.get("key") or "").lower()
        if "enter" in key or "return" in key:
            return "external_write"
        return "local_prepare"

    if name == "browser_network_request":
        method = (args.get("method") or "GET").upper()
        url = args.get("url") or ""
        return classify(method, url)

    if name == "browser_handle_dialog":
        action = (args.get("action") or "").lower()
        if action in ("accept", "confirm"):
            return "external_write"
        return "local_prepare"

    if name == "browser_fill_form":
        fields_str = str(args.get("fields") or {}).lower()
        if any(kw in fields_str for kw in _HIGH_IMPACT_KEYWORDS):
            return "high_impact_external_write"
        return "external_write"

    # Unknown MCP tool — conservative default.
    return "external_write"


def _mcp_action_phrase(name: str, args: dict, target: str) -> str:
    """Human description of what the browser action will do."""
    if name == "browser_click":
        return f"click '{target}'"
    if name == "browser_file_upload":
        paths = args.get("paths") or args.get("path")
        return f"upload local file(s) {paths} to the current page"
    if name == "browser_press_key":
        return f"press the '{args.get('key', '?')}' key"
    if name == "browser_network_request":
        method = (args.get("method") or "GET").upper()
        return f"send a {method} network request to {args.get('url', '?')}"
    if name == "browser_handle_dialog":
        return f"{args.get('action', 'handle')} a browser dialog"
    if name == "browser_fill_form":
        field_names = [
            str(f.get("name", "?")) for f in (args.get("fields") or [])
            if isinstance(f, dict)
        ]
        suffix = f" (fields: {', '.join(field_names)})" if field_names else ""
        return f"fill a form{suffix}"
    if name in ("browser_evaluate", "browser_run_code_unsafe"):
        return "execute JavaScript in the live page"
    return f"perform browser action '{name}'"


def _mcp_high_impact_reason(name: str, args: dict, target: str) -> str | None:
    if name == "browser_file_upload":
        return "uploads local files or documents to an external site"
    if name in ("browser_evaluate", "browser_run_code_unsafe"):
        return "executes arbitrary code in the live page"
    if name == "browser_click":
        kws = [kw for kw in _CLICK_HIGH_IMPACT_KEYWORDS if kw in (target or "").lower()]
        if kws:
            return f"click target matches high-impact keyword(s): {', '.join(kws)}"
    if name == "browser_fill_form":
        kws = _matched_high_impact_keywords(str(args.get("fields") or {}))
        if kws:
            return f"form fields match high-impact keyword(s): {', '.join(kws)}"
    return None


def _mcp_summary(tool: str, name: str, args: dict, target: str, action_class: str) -> str:
    high = action_class == "high_impact_external_write"
    domain = _extract_domain(args.get("url"), target)
    where = f" on {domain}" if domain else " in the browser"
    effect = (
        "This may trigger a high-impact, externally visible action "
        "(payment, submission, deletion, upload, or similar)."
        if high
        else "This may send data to or change state on the site."
    )
    return (
        f"Odysseus is about to {_mcp_action_phrase(name, args, target)}{where} "
        f"using MCP tool {tool}. {effect} Approval is required before execution."
    )


def guard_mcp(tool: str, args: dict, confirmed: bool) -> dict | None:
    """
    Return a pending_confirmation dict when the MCP tool action needs user
    confirmation, or None when execution should proceed.

    ``confirmed`` must already be stripped from ``args`` before forwarding
    to the MCP server.
    """
    action_class = classify_mcp_tool(tool, args)
    if action_class in ("safe_read", "local_prepare"):
        return None
    if confirmed:
        return None

    name = _bare_mcp_tool_name(tool)
    target = str(
        args.get("element")
        or args.get("url")
        or args.get("path")
        or args.get("selector")
        or args.get("ref")
        or name
    )
    url = args.get("url") if isinstance(args.get("url"), str) else None
    return build_preview(
        tool=tool,
        method="BROWSER_ACTION",
        target=target,
        body=args or None,
        action_class=action_class,
        action_name=name,
        url=url,
        summary=_mcp_summary(tool, name, args, target, action_class),
        high_impact_reason=_mcp_high_impact_reason(name, args, target),
    )
