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


def build_preview(
    *,
    tool: str,
    method: str,
    target: str,
    body: Any = None,
    integration: str | None = None,
    action_class: str,
) -> dict:
    high = action_class == "high_impact_external_write"
    risk = (
        "HIGH IMPACT: This action may be financially, legally, or security-sensitive "
        "and cannot be automatically reversed."
        if high
        else "This action mutates external or server-side state and cannot be undone automatically."
    )
    preview: dict[str, Any] = {
        "pending_confirmation": True,
        "tool": tool,
        "action_type": action_class,
        "method": method.upper(),
        "target": target,
        "risk": risk,
        "instruction": (
            "Show this preview to the user and ask for explicit approval before proceeding. "
            "Re-call with confirmed=true to execute."
        ),
    }
    if integration:
        preview["integration"] = integration
    if body is not None:
        preview["body_preview"] = body
    if high:
        preview["final_checklist"] = {
            "target": target,
            "method": method.upper(),
            "service": integration or "unknown",
            "body": body,
            "financial_impact": "unknown — review before confirming",
            "legal_consequence": "unknown — review before confirming",
        }
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
    "checkout", "cancel", "refund", "delete", "remove", "apply",
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

    target = str(
        args.get("element")
        or args.get("url")
        or args.get("path")
        or args.get("selector")
        or args.get("ref")
        or _bare_mcp_tool_name(tool)
    )
    return build_preview(
        tool=tool,
        method="BROWSER_ACTION",
        target=target,
        body=args or None,
        action_class=action_class,
    )
