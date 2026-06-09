"""Small browser-operator helpers for MCP-backed browser tasks."""
from __future__ import annotations

from typing import Any


BROWSER_OPERATOR_RULES = """\

## Browser operator workflow
- For browser tasks, first inspect the page with safe read tools such as snapshot, screenshot, console/network inspection, or navigation when needed.
- Summarize what you see for the user: page title/URL if available, visible purpose, important fields/buttons/links, safe next actions, and risky actions that need approval.
- Drafting/preparing fields is allowed when the tool is a local prepare action. Do not submit, send, upload, buy, cancel, refund, return, delete, change account/settings/security/payment/tax/legal/admin state, or run page code without current-chat approval.
- If a browser action returns `pending_confirmation`, show the preview to the user and wait. Only after explicit current-chat approval should you retry the same MCP tool with `confirmed=true` and the same action arguments.
- After a confirmed browser action, report what happened from the tool result; do not claim success if the browser/MCP tool failed or was unavailable."""


def is_browser_mcp_tool_name(name: str | None) -> bool:
    text = str(name or "")
    bare = text.rsplit("__", 1)[-1] if "__" in text else text
    return bare.startswith("browser_")


def format_confirmation_preview(preview: dict[str, Any]) -> str:
    """Human-readable confirmation preview for chat/tool output surfaces."""
    tool = preview.get("tool_name") or preview.get("tool") or "tool"
    action = preview.get("action_name") or preview.get("method") or preview.get("action") or "action"
    target = preview.get("target") or preview.get("target_url") or preview.get("target_resource") or "unknown target"
    risk = preview.get("risk_level") or ("high" if preview.get("high_impact") else "normal")
    lines = [
        "Confirmation required before execution.",
        f"Tool/action: {tool} / {action}",
        f"Target: {target}",
        f"Risk: {risk}",
    ]
    if preview.get("target_domain"):
        lines.append(f"Domain: {preview['target_domain']}")
    if preview.get("summary"):
        lines.append(f"Summary: {preview['summary']}")
    if preview.get("consequences"):
        lines.append(f"Consequence: {preview['consequences']}")
    if preview.get("high_impact_reason"):
        lines.append(f"Why approval is required: {preview['high_impact_reason']}")
    if preview.get("approval_instruction") or preview.get("instruction"):
        lines.append(f"Next step: {preview.get('approval_instruction') or preview.get('instruction')}")
    checklist = preview.get("final_review_checklist")
    if isinstance(checklist, list) and checklist:
        lines.append("Review checklist:")
        lines.extend(f"- {item}" for item in checklist[:6])
    return "\n".join(lines)


def format_browser_observation(tool: str, result: dict[str, Any]) -> str | None:
    """Readable browser read/prepare result for the operator path."""
    if not is_browser_mcp_tool_name(tool):
        return None
    if result.get("pending_confirmation"):
        return format_confirmation_preview(result)
    content = result.get("content") or result.get("output") or result.get("results")
    if content:
        label = tool.rsplit("__", 1)[-1] if "__" in tool else tool
        return f"Browser observation ({label}):\n{str(content)[:4000]}"
    if result.get("images"):
        label = tool.rsplit("__", 1)[-1] if "__" in tool else tool
        return f"Browser observation ({label}): screenshot captured."
    return None
