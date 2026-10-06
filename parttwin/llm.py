from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def explain_investigation(payload: dict) -> str | None:
    """Optional narrative polish. Failures must never block the deterministic engine."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    body = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 400,
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are PartTwin, an engineering investigation assistant. "
                    "Write a short, cautious briefing (max 180 words) for an engineer. "
                    "Do not certify parts. Stress that recommendations are potential only. "
                    "Use only the JSON facts. No markdown headings.\n\n"
                    + json.dumps(payload, default=str)[:6000]
                ),
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data.get("content") or []
        texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
        return "\n".join(texts) if texts else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None
