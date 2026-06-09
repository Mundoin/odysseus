"""Small browser-operator helpers for MCP-backed browser tasks."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


BROWSER_OPERATOR_RULES = """\

## Browser operator workflow
- For browser tasks, first inspect the page with safe read tools such as snapshot, screenshot, console/network inspection, or navigation when needed.
- Summarize what you see for the user: page title/URL if available, visible purpose, important fields/buttons/links, safe next actions, and risky actions that need approval.
- Drafting/preparing fields is allowed when the tool is a local prepare action. Do not submit, send, upload, buy, cancel, refund, return, delete, change account/settings/security/payment/tax/legal/admin state, or run page code without current-chat approval.
- If a browser action returns `pending_confirmation`, show the preview to the user and wait. Only after explicit current-chat approval should you retry the same MCP tool with `confirmed=true` and the same action arguments.
- After a confirmed browser action, report what happened from the tool result; do not claim success if the browser/MCP tool failed or was unavailable."""


_PENDING_BROWSER_ACTIONS: dict[str, set[str]] = {}
_SENSITIVE_KEYWORDS = (
    "password", "passwd", "token", "auth", "authorization", "secret",
    "api_key", "apikey", "card", "cvv", "cvc", "ssn", "social_security",
    "personal_id", "private_message",
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|token|auth(?:entication)?(?:[_ -]?code)?|authorization|"
    r"secret|api[_ -]?key|card(?:[_ -]?number)?|cvv|cvc|ssn|social[_ -]?security|"
    r"personal[_ -]?id|private[_ -]?message)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def is_browser_mcp_tool_name(name: str | None) -> bool:
    text = str(name or "")
    bare = text.rsplit("__", 1)[-1] if "__" in text else text
    return bare.startswith("browser_")


def _bare_tool_name(name: str | None) -> str:
    text = str(name or "")
    return text.rsplit("__", 1)[-1] if "__" in text else text


def browser_action_scope(session_id: str | None = None, owner: str | None = None) -> str:
    """Scope pending approvals to the current chat when possible."""
    if session_id:
        return f"session:{session_id}"
    if owner:
        return f"owner:{owner}"
    return "browser:unscoped"


def clear_browser_pending_actions() -> None:
    """Test/support helper for clearing in-memory pending browser approvals."""
    _PENDING_BROWSER_ACTIONS.clear()


def _normalise_for_fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _normalise_for_fingerprint(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) != "confirmed"
        }
    if isinstance(value, list):
        return [_normalise_for_fingerprint(item) for item in value]
    return value


def _target_from_args(args: dict[str, Any]) -> str:
    return str(
        args.get("element")
        or args.get("url")
        or args.get("target_url")
        or args.get("target")
        or args.get("path")
        or args.get("selector")
        or args.get("ref")
        or ""
    )


def browser_action_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    """Stable hash for exactly the browser action the user approved."""
    payload = {
        "tool_name": str(tool_name or ""),
        "action_name": _bare_tool_name(tool_name),
        "target": _target_from_args(args),
        "arguments": _normalise_for_fingerprint(args),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def attach_browser_action_fingerprint(
    preview: dict[str, Any],
    *,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(preview)
    fingerprint = browser_action_fingerprint(tool_name, args)
    enriched.setdefault("action_fingerprint", fingerprint)
    enriched.setdefault("preview_id", f"browser-action:{fingerprint[:16]}")
    return enriched


def record_browser_pending_action(
    scope: str,
    tool_name: str,
    args: dict[str, Any],
    preview: dict[str, Any],
) -> dict[str, Any]:
    enriched = attach_browser_action_fingerprint(preview, tool_name=tool_name, args=args)
    _PENDING_BROWSER_ACTIONS.setdefault(scope, set()).add(enriched["action_fingerprint"])
    return enriched


def consume_browser_pending_action(scope: str, tool_name: str, args: dict[str, Any]) -> bool:
    fingerprint = browser_action_fingerprint(tool_name, args)
    pending = _PENDING_BROWSER_ACTIONS.get(scope)
    if not pending or fingerprint not in pending:
        return False
    pending.remove(fingerprint)
    if not pending:
        _PENDING_BROWSER_ACTIONS.pop(scope, None)
    return True


def mark_browser_approval_mismatch(preview: dict[str, Any]) -> dict[str, Any]:
    updated = dict(preview)
    updated["approval_mismatch"] = True
    updated["approval_instruction"] = (
        "No matching pending browser approval exists for this exact tool/action/"
        "target/arguments. Show this fresh preview to the user and ask for "
        "explicit approval before retrying the same call with confirmed=true."
    )
    updated["instruction"] = updated["approval_instruction"]
    return updated


def redact_sensitive_text(text: Any) -> str:
    value = str(text)
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _SENSITIVE_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}: [REDACTED]", value)
    value = _CARD_RE.sub("[REDACTED_CARD]", value)
    return value


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS)


def redact_sensitive_value(value: Any, key: str | None = None) -> Any:
    if key and _looks_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_sensitive_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def confirmation_preview_for_event(preview: dict[str, Any]) -> dict[str, Any]:
    """Copy a confirmation preview for stream/history without leaking secrets."""
    return redact_sensitive_value(copy.deepcopy(preview))


def format_confirmation_preview(preview: dict[str, Any]) -> str:
    """Human-readable confirmation preview for chat/tool output surfaces."""
    safe_preview = confirmation_preview_for_event(preview)
    tool = safe_preview.get("tool_name") or safe_preview.get("tool") or "tool"
    action = safe_preview.get("action_name") or safe_preview.get("method") or safe_preview.get("action") or "action"
    target = safe_preview.get("target") or safe_preview.get("target_url") or safe_preview.get("target_resource") or "unknown target"
    risk = safe_preview.get("risk_level") or ("high" if safe_preview.get("high_impact") else "normal")
    lines = [
        "Confirmation required before execution.",
        f"Tool/action: {tool} / {action}",
        f"Target: {target}",
        f"Risk: {risk}",
    ]
    if safe_preview.get("target_domain"):
        lines.append(f"Domain: {safe_preview['target_domain']}")
    if safe_preview.get("summary"):
        lines.append(f"Summary: {safe_preview['summary']}")
    if safe_preview.get("consequences"):
        lines.append(f"Consequence: {safe_preview['consequences']}")
    if safe_preview.get("high_impact_reason"):
        lines.append(f"Why approval is required: {safe_preview['high_impact_reason']}")
    if safe_preview.get("action_fingerprint"):
        lines.append(f"Action fingerprint: {safe_preview['action_fingerprint']}")
    if safe_preview.get("preview_id"):
        lines.append(f"Preview ID: {safe_preview['preview_id']}")
    if safe_preview.get("approval_instruction") or safe_preview.get("instruction"):
        lines.append(f"Next step: {safe_preview.get('approval_instruction') or safe_preview.get('instruction')}")
    checklist = safe_preview.get("final_review_checklist")
    if isinstance(checklist, list) and checklist:
        lines.append("Review checklist:")
        lines.extend(f"- {item}" for item in checklist[:6])
    return "\n".join(lines)


def _extract_labeled_line(content: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+)$", content)
    return match.group(1).strip() if match else None


def _extract_action_lines(content: str) -> list[str]:
    actions: list[str] = []
    for label in ("Buttons", "Links", "Fields", "Forms", "Actions"):
        value = _extract_labeled_line(content, label)
        if value:
            actions.append(f"{label}: {value}")
    return actions


def format_browser_observation(tool: str, result: dict[str, Any]) -> str | None:
    """Readable browser read/prepare result for the operator path."""
    if not is_browser_mcp_tool_name(tool):
        return None
    if result.get("pending_confirmation"):
        return format_confirmation_preview(result)
    content = result.get("content") or result.get("output") or result.get("results")
    if content:
        label = tool.rsplit("__", 1)[-1] if "__" in tool else tool
        safe_content = redact_sensitive_text(str(content))[:3200]
        title = _extract_labeled_line(safe_content, "Title")
        url = _extract_labeled_line(safe_content, "URL")
        action_lines = _extract_action_lines(safe_content)
        lines = [f"Browser observation ({label}):", "Observed page facts:"]
        if title:
            lines.append(f"- Title: {title}")
        if url:
            lines.append(f"- URL: {url}")
        lines.append(f"- Visible content summary: {safe_content}")
        lines.append("Detected forms/buttons/actions:")
        lines.extend(f"- {item}" for item in action_lines[:8])
        if not action_lines:
            lines.append("- None explicitly detected in the tool output.")
        lines.append("Inferred next steps:")
        lines.append("- Safe: inspect, summarize, navigate/read, or prepare form fields.")
        lines.append("Risky actions requiring approval:")
        lines.append("- submit/send/upload/buy/cancel/refund/return/delete/payment/account/security/admin actions.")
        return "\n".join(lines)
    if result.get("images"):
        label = tool.rsplit("__", 1)[-1] if "__" in tool else tool
        return f"Browser observation ({label}): screenshot captured."
    return None
