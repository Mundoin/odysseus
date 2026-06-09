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


_RISKY_CONTROL_KEYWORDS = (
    "submit", "send", "upload", "buy", "pay", "delete", "cancel", "refund",
    "return", "confirm", "apply", "login", "sign in", "security", "account",
    "payment", "legal", "admin", "checkout", "purchase", "order",
)
_SAFE_CONTROL_KEYWORDS = (
    "read", "view", "search", "filter", "expand", "open", "details", "help",
    "learn", "more", "next", "previous", "back", "close", "menu",
)


def _compact_text(value: Any, limit: int = 900) -> str:
    text = redact_sensitive_text(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _content_payload(result: dict[str, Any] | Any) -> Any:
    if isinstance(result, dict):
        for key in ("content", "output", "results", "snapshot", "page"):
            if key in result and result[key] not in (None, ""):
                return result[key]
    return result


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _text_from_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "label", "name", "title", "url"):
            if isinstance(value.get(key), str):
                parts.append(value[key])
        for key in ("children", "items", "nodes", "blocks"):
            if key in value:
                child_text = _text_from_payload(value[key])
                if child_text:
                    parts.append(child_text)
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(_text_from_payload(item) for item in value)
    return str(value) if value is not None else ""


def _first_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return redact_sensitive_text(found.strip())
    for item in _iter_dicts(value):
        for key in keys:
            found = item.get(key)
            if isinstance(found, str) and found.strip():
                return redact_sensitive_text(found.strip())
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _split_labeled_values(text: str, label: str) -> list[str]:
    value = _extract_labeled_line(text, label)
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()]


def classify_browser_control(text: str, target: str | None = None, control_type: str | None = None) -> str:
    haystack = " ".join(
        part.lower()
        for part in (text or "", target or "", control_type or "")
        if part
    )
    if any(keyword in haystack for keyword in _RISKY_CONTROL_KEYWORDS):
        return "risky"
    if any(keyword in haystack for keyword in _SAFE_CONTROL_KEYWORDS):
        return "safe"
    return "unknown"


def _required_state(value: Any) -> str:
    if value is True:
        return "required"
    if value is False:
        return "optional"
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("required", "true", "yes"):
            return "required"
        if lowered in ("optional", "false", "no"):
            return "optional"
    return "unknown"


def _candidate_meaning(label: str, name: str, field_type: str) -> str:
    text = " ".join((label, name, field_type)).lower()
    if "email" in text:
        return "email address"
    if "password" in text:
        return "password or secret"
    if "search" in text or name == "q":
        return "search query"
    if "card" in text or "payment" in text:
        return "payment data"
    if "message" in text:
        return "message text"
    if "file" in text or "upload" in text:
        return "file upload"
    return "unknown"


def _normalise_link(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        text = item.get("text") or item.get("label") or item.get("name") or item.get("title") or item.get("href") or item.get("url") or ""
        target = item.get("href") or item.get("target") or item.get("url")
    else:
        text = str(item)
        target = None
    text = redact_sensitive_text(text)
    target = redact_sensitive_text(target) if target else None
    classification = classify_browser_control(text, target, "link")
    return {"text": text, "href": target, "classification": classification}


def _normalise_button(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        text = item.get("text") or item.get("label") or item.get("name") or item.get("title") or item.get("value") or ""
        role = item.get("role") or "button"
        control_type = item.get("type") or role
    else:
        text = str(item)
        role = "button"
        control_type = "button"
    text = redact_sensitive_text(text)
    control_type = redact_sensitive_text(control_type)
    classification = classify_browser_control(text, None, control_type)
    return {
        "text": text,
        "label": text,
        "role": role,
        "type": control_type,
        "classification": classification,
    }


def _normalise_field(item: Any) -> dict[str, Any]:
    item = item if isinstance(item, dict) else {"label": str(item)}
    label = redact_sensitive_text(item.get("label") or item.get("text") or item.get("name") or "")
    name = redact_sensitive_text(item.get("name") or "")
    field_id = redact_sensitive_text(item.get("id") or "")
    field_type = redact_sensitive_text(item.get("type") or item.get("input_type") or "unknown")
    raw_value = item.get("value") or item.get("current_value") or ""
    key_hint = name or label or field_type
    redacted_value = redact_sensitive_value(raw_value, key_hint) if raw_value != "" else ""
    return {
        "label": label,
        "name": name,
        "id": field_id,
        "type": field_type,
        "required": _required_state(item.get("required")),
        "current_value_redacted": redacted_value,
        "candidate_meaning": _candidate_meaning(label, name, field_type),
        "accepted_types": redact_sensitive_text(item.get("accept") or item.get("accepted_types") or item.get("accepts") or ""),
    }


def _normalise_upload_field(item: Any) -> dict[str, Any]:
    field = _normalise_field(item)
    if isinstance(item, dict):
        accepted = item.get("accept") or item.get("accepted_types") or item.get("accepts")
    else:
        accepted = None
    return {
        "label": field["label"],
        "name": field["name"],
        "id": field["id"],
        "accepted_types": redact_sensitive_text(accepted) if accepted else "unknown",
        "required": field["required"],
    }


def _normalise_form(item: Any) -> dict[str, Any]:
    item = item if isinstance(item, dict) else {"name": str(item)}
    return {
        "name": redact_sensitive_text(item.get("name") or ""),
        "id": redact_sensitive_text(item.get("id") or ""),
        "action": redact_sensitive_text(item.get("action") or item.get("target") or ""),
        "fields": redact_sensitive_value(item.get("fields") or item.get("inputs") or []),
        "submit_actions": redact_sensitive_value(item.get("submit_actions") or item.get("buttons") or []),
    }


def _structured_items(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    items: list[Any] = []
    if isinstance(payload, dict):
        for key in keys:
            items.extend(_as_list(payload.get(key)))
    role_map = {
        "links": {"link", "a"},
        "buttons": {"button"},
        "fields": {"textbox", "input", "combobox", "checkbox", "radio", "searchbox"},
    }
    wanted = role_map.get(keys[0], set())
    for node in _iter_dicts(payload):
        role = str(node.get("role") or node.get("tag") or "").lower()
        if role in wanted and node not in items:
            items.append(node)
    return [item for item in items if item not in (None, "")]


def _safe_and_risky_actions(inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safe: list[dict[str, Any]] = []
    risky: list[dict[str, Any]] = []
    for link in inventory["links"]:
        action = {
            "action": "navigate",
            "target": link.get("text") or link.get("href") or "link",
            "reason": f"link classified as {link['classification']}",
        }
        if link["classification"] == "risky":
            risky.append({**action, "requires_approval": True})
        elif link["classification"] == "safe":
            safe.append(action)
    for button in inventory["buttons"]:
        action = {
            "action": "click",
            "target": button.get("text") or "button",
            "reason": f"button classified as {button['classification']}",
        }
        if button["classification"] == "risky":
            risky.append({**action, "requires_approval": True})
        elif button["classification"] == "safe":
            safe.append(action)
    for upload in inventory["upload_fields"]:
        risky.append({
            "action": "upload",
            "target": upload.get("label") or upload.get("name") or "file input",
            "reason": "file upload can disclose local files to a site",
            "requires_approval": True,
        })
    return safe, risky


def build_page_inventory(result: dict[str, Any] | Any) -> dict[str, Any]:
    """Build a defensive page inventory from browser/MCP snapshot output."""
    payload = _content_payload(result)
    text = redact_sensitive_text(_text_from_payload(payload))
    title = _first_string(payload, ("title", "page_title")) or _extract_labeled_line(text, "Title")
    url = _first_string(payload, ("url", "href", "current_url")) or _extract_labeled_line(text, "URL")

    links = [_normalise_link(item) for item in _structured_items(payload, ("links", "anchors"))]
    buttons = [_normalise_button(item) for item in _structured_items(payload, ("buttons", "actions"))]
    fields = [_normalise_field(item) for item in _structured_items(payload, ("fields", "inputs"))]
    upload_fields = [
        _normalise_upload_field(item)
        for item in _structured_items(payload, ("upload_fields", "file_inputs"))
    ]

    if not links:
        links = [_normalise_link(item) for item in _split_labeled_values(text, "Links")]
    if not buttons:
        buttons = [_normalise_button(item) for item in _split_labeled_values(text, "Buttons")]
    if not fields:
        fields = [_normalise_field(item) for item in _split_labeled_values(text, "Fields")]

    for field in fields:
        if field.get("type", "").lower() == "file" or "upload" in (field.get("candidate_meaning") or ""):
            upload = {
                "label": field.get("label", ""),
                "name": field.get("name", ""),
                "id": field.get("id", ""),
                "accepted_types": field.get("accepted_types") or "unknown",
                "required": field.get("required", "unknown"),
            }
            if upload not in upload_fields:
                upload_fields.append(upload)

    forms = [_normalise_form(item) for item in _structured_items(payload, ("forms",))]
    inventory = {
        "url": url or "",
        "title": title or "",
        "visible_text_summary": _compact_text(text),
        "links": links,
        "buttons": buttons,
        "fields": fields,
        "upload_fields": upload_fields,
        "forms": forms,
        "risky_actions": [],
        "safe_actions": [],
    }
    inventory["safe_actions"], inventory["risky_actions"] = _safe_and_risky_actions(inventory)
    return inventory


def _format_inventory_list(label: str, items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    lines = [label]
    if not items:
        lines.append("- None detected.")
        return lines
    for item in items[:10]:
        details = []
        for field in fields:
            value = item.get(field)
            if value not in (None, "", []):
                details.append(f"{field}={value}")
        lines.append(f"- {', '.join(details) if details else item}")
    return lines


def format_page_inventory(inventory: dict[str, Any]) -> str:
    lines = [
        "Page inventory",
        "Observed page facts:",
        f"- Title: {inventory.get('title') or 'unknown'}",
        f"- URL: {inventory.get('url') or 'unknown'}",
        f"- Visible text summary: {inventory.get('visible_text_summary') or 'unknown'}",
    ]
    lines.extend(_format_inventory_list("Detected links:", inventory["links"], ("text", "href", "classification")))
    lines.extend(_format_inventory_list("Detected buttons:", inventory["buttons"], ("text", "type", "classification")))
    lines.extend(_format_inventory_list("Detected fields:", inventory["fields"], ("label", "name", "type", "required", "candidate_meaning", "current_value_redacted")))
    lines.extend(_format_inventory_list("Detected upload fields:", inventory["upload_fields"], ("label", "name", "accepted_types", "required")))
    lines.extend(_format_inventory_list("Detected forms:", inventory["forms"], ("name", "id", "action", "fields", "submit_actions")))
    lines.extend(_format_inventory_list("Safe actions:", inventory["safe_actions"], ("action", "target", "reason")))
    lines.extend(_format_inventory_list("Risky actions requiring approval:", inventory["risky_actions"], ("action", "target", "reason", "requires_approval")))
    lines.append("Unknowns/questions for the user:")
    if not inventory["fields"] and not inventory["buttons"] and not inventory["links"]:
        lines.append("- Snapshot did not expose controls; inspect a richer snapshot before acting.")
    else:
        lines.append("- Confirm intent before filling, uploading, submitting, or changing account/payment/security state.")
    return "\n".join(lines)


_FIELD_VALUE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("first_name", ("first name", "firstname", "given name", "vorname")),
    ("last_name", ("last name", "lastname", "surname", "nachname")),
    ("email", ("email", "e-mail", "mail")),
    ("phone", ("phone", "mobile", "telefon", "telephone", "tel")),
    ("address", ("address", "street", "strasse", "straße")),
    ("city", ("city", "ort", "stadt")),
    ("postcode", ("postcode", "postal code", "zip", "plz")),
    ("country", ("country", "land")),
    ("linkedin", ("linkedin", "linked in")),
    ("github", ("github", "git hub")),
    ("website", ("website", "portfolio", "homepage")),
    ("cover_letter", ("cover letter", "motivation", "anschreiben")),
    ("salary_expectation", ("salary expectation", "gehaltsvorstellung")),
    ("availability", ("availability", "start date", "frühester eintritt", "fruehester eintritt")),
)
_SENSITIVE_FIELD_KEYWORDS = (
    "password", "passwd", "token", "auth code", "api key", "apikey", "secret",
    "payment card", "card number", "credit card", "cvv", "cvc", "iban",
    "bank", "national id", "passport", "personalausweis", "tax id", "tax",
    "health", "medical", "private message",
)


def _field_ref(field: dict[str, Any], index: int) -> str:
    return str(field.get("id") or field.get("name") or field.get("label") or f"field_{index + 1}")


def _field_identity(field: dict[str, Any]) -> str:
    return " ".join(
        str(field.get(key) or "")
        for key in ("label", "name", "id", "type", "candidate_meaning")
    ).lower()


def _known_value_key_for_field(field: dict[str, Any]) -> str | None:
    identity = _field_identity(field)
    compact = re.sub(r"[^a-z0-9äöüß]+", "", identity)
    for key, aliases in _FIELD_VALUE_ALIASES:
        for alias in aliases:
            alias_text = alias.lower()
            alias_compact = re.sub(r"[^a-z0-9äöüß]+", "", alias_text)
            if alias_text in identity or alias_compact in compact:
                return key
    return None


def _is_sensitive_form_field(field: dict[str, Any]) -> tuple[bool, str]:
    identity = _field_identity(field)
    if str(field.get("type") or "").lower() == "password":
        return True, "password fields must be filled manually or with explicit user direction"
    for keyword in _SENSITIVE_FIELD_KEYWORDS:
        if keyword in identity:
            return True, f"field matches sensitive keyword '{keyword}'"
    return False, ""


def _document_candidate_for_upload(
    upload: dict[str, Any],
    document_candidates: dict[str, Any],
) -> Any:
    identity = " ".join(
        str(upload.get(key) or "")
        for key in ("label", "name", "id", "accepted_types")
    ).lower()
    candidate_aliases = (
        ("cv", ("cv", "resume", "lebenslauf")),
        ("cover_letter", ("cover letter", "motivation", "anschreiben")),
        ("certificate", ("certificate", "certification", "zeugnis", "diploma")),
    )
    for key, aliases in candidate_aliases:
        if any(alias in identity for alias in aliases) and key in document_candidates:
            return redact_sensitive_value(document_candidates[key], key)
    return ""


def _plan_confidence(fields_total: int, fields_mapped: int, missing: int, sensitive: int) -> str:
    if fields_total == 0:
        return "low"
    ratio = fields_mapped / fields_total
    if ratio >= 0.75 and missing == 0 and sensitive == 0:
        return "high"
    if ratio >= 0.4:
        return "medium"
    return "low"


def _value_preview(value: Any, key: str) -> Any:
    redacted = redact_sensitive_value(value, key)
    if isinstance(redacted, str):
        redacted = re.sub(r"(?i)\bprivate\s+message\b", "[REDACTED]", redacted)
        return redact_sensitive_text(redacted)[:160]
    return redacted


def build_form_fill_plan(
    page_inventory: dict[str, Any],
    known_values: dict[str, Any] | None = None,
    document_candidates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a safe, redacted form-fill plan from a page inventory."""
    known_values = known_values or {}
    document_candidates = document_candidates or {}
    fill_steps: list[dict[str, Any]] = []
    missing_values: list[dict[str, Any]] = []
    sensitive_values: list[dict[str, Any]] = []
    upload_steps: list[dict[str, Any]] = []
    blocked_actions: list[dict[str, Any]] = []
    next_safe_actions: list[dict[str, Any]] = []

    fields = page_inventory.get("fields") or []
    upload_refs = {
        (upload.get("id"), upload.get("name"), upload.get("label"))
        for upload in page_inventory.get("upload_fields") or []
    }
    fields_total = 0

    for index, field in enumerate(fields):
        field_type = str(field.get("type") or "unknown")
        is_upload = (
            field_type.lower() == "file"
            or field.get("candidate_meaning") == "file upload"
            or (field.get("id"), field.get("name"), field.get("label")) in upload_refs
        )
        if is_upload:
            continue
        fields_total += 1
        ref = _field_ref(field, index)
        sensitive, reason = _is_sensitive_form_field(field)
        if sensitive:
            sensitive_values.append({
                "field_ref": ref,
                "label": field.get("label", ""),
                "name": field.get("name", ""),
                "id": field.get("id", ""),
                "field_type": field_type,
                "required": field.get("required", "unknown"),
                "reason": reason,
                "requires_user_confirmation": True,
            })
            continue

        value_key = _known_value_key_for_field(field)
        if value_key and value_key in known_values and known_values[value_key] not in (None, ""):
            fill_steps.append({
                "field_ref": ref,
                "label": field.get("label", ""),
                "name": field.get("name", ""),
                "id": field.get("id", ""),
                "field_type": field_type,
                "value_preview_redacted": _value_preview(known_values[value_key], value_key),
                "value_source": f"known_values.{value_key}",
                "confidence": "high",
                "safe_to_fill": True,
                "reason": f"mapped field to known value '{value_key}'",
            })
        else:
            label = field.get("label") or field.get("name") or ref
            missing_values.append({
                "field_ref": ref,
                "label": field.get("label", ""),
                "name": field.get("name", ""),
                "id": field.get("id", ""),
                "field_type": field_type,
                "question_for_user": f"What value should I use for {label}?",
                "reason": "no matching known value was available",
            })

    seen_upload_refs: set[str] = set()
    for index, upload in enumerate(page_inventory.get("upload_fields") or []):
        ref = _field_ref(upload, index)
        if ref in seen_upload_refs:
            continue
        seen_upload_refs.add(ref)
        upload_steps.append({
            "field_ref": ref,
            "label": upload.get("label", ""),
            "name": upload.get("name", ""),
            "id": upload.get("id", ""),
            "accepted_types": upload.get("accepted_types", "unknown"),
            "candidate_document": _document_candidate_for_upload(upload, document_candidates),
            "requires_approval": True,
            "reason": "file uploads can disclose local documents and require approval",
        })

    for action in page_inventory.get("risky_actions") or []:
        blocked_actions.append({
            "action": action.get("action", "action"),
            "target": action.get("target", ""),
            "reason": action.get("reason", "risky browser action requires approval"),
            "requires_approval": True,
        })
    for action in page_inventory.get("safe_actions") or []:
        next_safe_actions.append({
            "action": action.get("action", "action"),
            "target": action.get("target", ""),
            "reason": action.get("reason", "safe browser action"),
        })
    for step in fill_steps:
        next_safe_actions.append({
            "action": "fill",
            "target": step["field_ref"],
            "reason": step["reason"],
        })

    return {
        "page_url": page_inventory.get("url", ""),
        "page_title": page_inventory.get("title", ""),
        "confidence": _plan_confidence(fields_total, len(fill_steps), len(missing_values), len(sensitive_values)),
        "fields_total": fields_total,
        "fields_mapped": len(fill_steps),
        "fields_missing": len(missing_values),
        "fields_sensitive": len(sensitive_values),
        "fill_steps": fill_steps,
        "missing_values": missing_values,
        "sensitive_values": sensitive_values,
        "upload_steps": upload_steps,
        "blocked_actions": blocked_actions,
        "next_safe_actions": next_safe_actions,
    }


def _format_plan_list(label: str, items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    lines = [label]
    if not items:
        lines.append("- None.")
        return lines
    for item in items[:12]:
        details = []
        for field in fields:
            value = item.get(field)
            if value not in (None, "", []):
                details.append(f"{field}={value}")
        lines.append(f"- {', '.join(details) if details else item}")
    return lines


def format_form_fill_plan(plan: dict[str, Any]) -> str:
    lines = [
        "Form fill plan",
        f"- Page title: {plan.get('page_title') or 'unknown'}",
        f"- Page URL: {plan.get('page_url') or 'unknown'}",
        f"- Confidence: {plan.get('confidence') or 'unknown'}",
        f"- Fields total/mapped/missing/sensitive: "
        f"{plan.get('fields_total', 0)}/{plan.get('fields_mapped', 0)}/"
        f"{plan.get('fields_missing', 0)}/{plan.get('fields_sensitive', 0)}",
    ]
    lines.extend(_format_plan_list(
        "Mapped fill steps:",
        plan.get("fill_steps") or [],
        ("field_ref", "label", "name", "field_type", "value_preview_redacted", "value_source", "safe_to_fill", "reason"),
    ))
    lines.extend(_format_plan_list(
        "Missing values/questions:",
        plan.get("missing_values") or [],
        ("field_ref", "label", "name", "field_type", "question_for_user", "reason"),
    ))
    lines.extend(_format_plan_list(
        "Sensitive fields needing manual decision:",
        plan.get("sensitive_values") or [],
        ("field_ref", "label", "name", "field_type", "required", "reason", "requires_user_confirmation"),
    ))
    lines.extend(_format_plan_list(
        "Upload steps requiring approval:",
        plan.get("upload_steps") or [],
        ("field_ref", "label", "name", "accepted_types", "candidate_document", "requires_approval", "reason"),
    ))
    lines.extend(_format_plan_list(
        "Blocked submit/payment/send/apply actions:",
        plan.get("blocked_actions") or [],
        ("action", "target", "reason", "requires_approval"),
    ))
    lines.extend(_format_plan_list(
        "Next safe actions:",
        plan.get("next_safe_actions") or [],
        ("action", "target", "reason"),
    ))
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
        inventory = build_page_inventory(result)
        lines = [f"Browser observation ({label}):", format_page_inventory(inventory)]
        lines.append("Inferred next steps:")
        lines.append("- Safe: inspect, summarize, navigate/read, or prepare form fields.")
        lines.append("- Ask before submitting, uploading, buying, deleting, or changing account/payment/security state.")
        return "\n".join(lines)
    if result.get("images"):
        label = tool.rsplit("__", 1)[-1] if "__" in tool else tool
        return f"Browser observation ({label}): screenshot captured."
    return None
