"""Read gpt-image live-try metrics written by stephens.page/gpt-image/try-submit.php.

Append-only JSONL at GPT_IMAGE_TRIALS_PATH. Dashboard never writes this file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TRIALS_PATH = Path(os.environ.get("GPT_IMAGE_TRIALS_PATH", "/var/lib/gpt-image/trials.jsonl"))


def _load_events(limit: int | None = None) -> list[dict]:
    if not TRIALS_PATH.is_file():
        return []
    events: list[dict] = []
    try:
        with TRIALS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    if limit is not None and limit > 0:
        return events[-limit:]
    return events


def stats() -> dict:
    """Aggregate trial log for the dashboard panel."""
    events = _load_events()
    tries = [e for e in events if e.get("event") == "try"]
    ok = [e for e in tries if e.get("ok")]
    fail = [e for e in tries if not e.get("ok")]
    emails = {str(e.get("email", "")).lower() for e in tries if e.get("email")}
    emails.discard("")
    recent = list(reversed(tries[-40:]))
    for e in recent:
        prompt = str(e.get("prompt") or "")
        if len(prompt) > 120:
            e["prompt_short"] = prompt[:117] + "..."
        else:
            e["prompt_short"] = prompt
    return {
        "path": str(TRIALS_PATH),
        "total_attempts": len(tries),
        "successes": len(ok),
        "failures": len(fail),
        "unique_emails": len(emails),
        "honeypots": sum(1 for e in events if e.get("event") == "honeypot"),
        "recent": recent,
        "error": None,
    }
