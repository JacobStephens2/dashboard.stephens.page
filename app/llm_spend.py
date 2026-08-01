"""Hello-ladder LLM spend (GPT-5.6 Luna) for dashboard tab.

Reads the durable ledger written by the blog runner at
/var/lib/hello-ladder/llm_spend.json (and optional events jsonl).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SPEND_PATH = Path(
    os.environ.get("HELLO_LADDER_SPEND_PATH", "/var/lib/hello-ladder/llm_spend.json")
)
EVENTS_PATH = Path(
    os.environ.get("HELLO_LADDER_EVENTS_PATH", "/var/lib/hello-ladder/llm_events.jsonl")
)
ALERT_USD = float(os.environ.get("HELLO_LADDER_SPEND_ALERT_USD", "5.0"))


def _empty() -> dict:
    return {
        "total_usd": 0.0,
        "request_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "currency": "USD",
        "model": "gpt-5.6-luna",
        "alert_threshold_usd": ALERT_USD,
        "alerted_5usd": False,
        "updated_at": 0,
        "note": "No spend recorded yet.",
        "last_request": None,
        "recent": [],
        "path": str(SPEND_PATH),
        "error": None,
    }


def stats() -> dict:
    data = _empty()
    if not SPEND_PATH.is_file():
        data["error"] = f"Spend file not found at {SPEND_PATH}"
        return data
    try:
        raw = json.loads(SPEND_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        data["error"] = str(exc)
        return data
    if not isinstance(raw, dict):
        data["error"] = "Spend file is not a JSON object"
        return data
    data.update(
        {
            "total_usd": float(raw.get("total_usd") or 0),
            "request_count": int(raw.get("request_count") or 0),
            "input_tokens": int(raw.get("input_tokens") or 0),
            "output_tokens": int(raw.get("output_tokens") or 0),
            "cached_input_tokens": int(raw.get("cached_input_tokens") or 0),
            "currency": str(raw.get("currency") or "USD"),
            "model": str(raw.get("model") or "gpt-5.6-luna"),
            "alert_threshold_usd": float(raw.get("alert_threshold_usd") or ALERT_USD),
            "alerted_5usd": bool(raw.get("alerted_5usd")),
            "updated_at": int(raw.get("updated_at") or 0),
            "note": str(raw.get("note") or data["note"]),
            "last_request": raw.get("last_request"),
            "error": None,
        }
    )
    data["remaining_to_alert"] = max(
        0.0, float(data["alert_threshold_usd"]) - float(data["total_usd"])
    )
    data["over_alert"] = float(data["total_usd"]) >= float(data["alert_threshold_usd"])
    data["recent"] = _recent_events(12)
    return data


def _recent_events(n: int) -> list[dict]:
    if not EVENTS_PATH.is_file():
        return []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    out.reverse()
    return out
