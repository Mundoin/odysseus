"""
One-shot repair: set supports_tools for model endpoints where the value is NULL
but the provider/model is known to support (or not support) function calling.

Run once after upgrade, or include in setup.py / app startup.

Safe to re-run: only touches rows where supports_tools IS NULL.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running from repo root without activating the venv explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Providers that support OpenAI-style function/tool calling via their cloud API.
# Match against the endpoint base_url (lowercased).
_TOOL_CAPABLE_URL_PATTERNS: list[str] = [
    r"api\.deepseek\.com",
    r"generativelanguage\.googleapis\.com",   # Gemini
    r"api\.moonshot\.cn",                      # Kimi / Moonshot
    r"open\.bigmodel\.cn",                     # Zhipu / GLM
    r"api\.zhipuai\.cn",
    r"api\.xiaomimimo\.com",                   # Mimo cloud
    r"api\.openai\.com",
    r"api\.anthropic\.com",
    r"api\.groq\.com",
    r"openrouter\.ai",
    r"api\.mistral\.ai",
    r"api\.cohere\.com",
    r"api\.together\.xyz",
    r"api\.fireworks\.ai",
]

# Model-name substrings that indicate the specific model does NOT support tools
# even when served via an otherwise tool-capable endpoint.
# Only applies when supports_tools is still NULL after the URL pass.
_NO_TOOL_MODEL_PATTERNS: list[str] = [
    "deepseek-r1",      # reasoning model — rejects tool schemas
]


def repair(db_path: str | None = None, dry_run: bool = False) -> dict[str, list[str]]:
    """
    Scan ModelEndpoint rows with supports_tools IS NULL and apply defaults.

    Returns a dict with keys 'set_true', 'set_false', 'skipped' listing endpoint names.
    """
    from core.database import SessionLocal, ModelEndpoint

    session = SessionLocal()
    results: dict[str, list[str]] = {"set_true": [], "set_false": [], "skipped": []}
    try:
        rows = session.query(ModelEndpoint).filter(ModelEndpoint.supports_tools.is_(None)).all()
        for ep in rows:
            url = (ep.base_url or "").lower()
            name = (ep.name or "").lower()

            # Check no-tool model patterns first (higher priority).
            if any(pat in name for pat in _NO_TOOL_MODEL_PATTERNS):
                if not dry_run:
                    ep.supports_tools = False
                results["set_false"].append(ep.name)
                continue

            # Check tool-capable URL patterns.
            if any(re.search(pat, url) for pat in _TOOL_CAPABLE_URL_PATTERNS):
                if not dry_run:
                    ep.supports_tools = True
                results["set_true"].append(ep.name)
                continue

            results["skipped"].append(ep.name)

        if not dry_run:
            session.commit()
    finally:
        session.close()

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    result = repair(dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    for ep in result["set_true"]:
        print(f"{prefix}supports_tools → True   {ep!r}")
    for ep in result["set_false"]:
        print(f"{prefix}supports_tools → False  {ep!r}")
    for ep in result["skipped"]:
        print(f"{prefix}skipped (unknown provider): {ep!r}")
    print(f"\n{prefix}Done. true={len(result['set_true'])} false={len(result['set_false'])} skipped={len(result['skipped'])}")
