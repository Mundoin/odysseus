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
