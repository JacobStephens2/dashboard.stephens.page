"""Inkvoke (live try) metrics + community gallery management.

Trial log is append-only JSONL written by stephens.page/inkvoke/try-submit.php
at GPT_IMAGE_TRIALS_PATH. Dashboard never writes that file.

Gallery images and manifest live under stephens.page/inkvoke/gallery/. Dashboard
can toggle ``hidden`` on manifest items so they drop off the public gallery and
hero slideshow without deleting the file. Hiding also removes that item's
``cost_usd`` from the public running spend tally; showing adds it back.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path

TRIALS_PATH = Path(os.environ.get("GPT_IMAGE_TRIALS_PATH", "/var/lib/gpt-image/trials.jsonl"))
GALLERY_DIR = Path(
    os.environ.get("INKVOKE_GALLERY_DIR", "/var/www/stephens.page/inkvoke/gallery")
)
GALLERY_MANIFEST = Path(
    os.environ.get("INKVOKE_GALLERY_MANIFEST", str(GALLERY_DIR / "manifest.json"))
)
PUBLIC_BASE = os.environ.get("INKVOKE_PUBLIC_BASE", "https://inkvoke.dev").rstrip("/")

SPEND_PATH = Path(os.environ.get("INKVOKE_SPEND_PATH", str(GALLERY_DIR / "spend.json")))
SPEND_PATH_LIB = Path(os.environ.get("INKVOKE_SPEND_PATH_LIB", "/var/lib/gpt-image/spend.json"))


def _item_cost_usd(item: dict) -> float:
    raw = item.get("cost_usd")
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def _read_spend_unlocked(fh) -> dict:
    raw = fh.read()
    empty = {"total_usd": 0.0, "image_count": 0, "updated_at": 0}
    if not raw or not str(raw).strip():
        return empty
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "total_usd": float(data.get("total_usd") or 0),
        "image_count": int(data.get("image_count") or 0),
        "updated_at": int(data.get("updated_at") or 0),
        "currency": str(data.get("currency") or "USD"),
        "note": str(
            data.get("note")
            or "Estimated live-try OpenAI image spend (gpt-image-2 rates). "
            "Hidden gallery images are excluded from this total."
        ),
    }


def adjust_spend_for_visibility(cost_usd: float, *, becoming_hidden: bool) -> dict | None:
    """Subtract cost when hiding a public item; add when un-hiding. Returns new spend or None."""
    cost = float(cost_usd or 0)
    if cost <= 0:
        return None
    delta = -cost if becoming_hidden else cost
    count_delta = -1 if becoming_hidden else 1

    path = SPEND_PATH if SPEND_PATH.parent.is_dir() else SPEND_PATH_LIB
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            json.dumps(
                {
                    "total_usd": 0.0,
                    "image_count": 0,
                    "updated_at": int(time.time()),
                    "currency": "USD",
                    "note": (
                        "Estimated live-try OpenAI image spend (gpt-image-2 rates). "
                        "Hidden gallery images are excluded from this total."
                    ),
                },
                ensure_ascii=False,
                indent=4,
            )
            + "\n",
            encoding="utf-8",
        )

    try:
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                cur = _read_spend_unlocked(fh)
                total = max(0.0, float(cur.get("total_usd") or 0) + delta)
                count = max(0, int(cur.get("image_count") or 0) + count_delta)
                payload = {
                    "total_usd": round(total, 6),
                    "image_count": count,
                    "updated_at": int(time.time()),
                    "currency": "USD",
                    "note": (
                        "Estimated live-try OpenAI image spend (gpt-image-2 rates). "
                        "Hidden gallery images are excluded from this total."
                    ),
                }
                blob = json.dumps(payload, ensure_ascii=False, indent=4) + "\n"
                fh.seek(0)
                fh.truncate()
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        other = SPEND_PATH_LIB if path.resolve() == SPEND_PATH.resolve() else SPEND_PATH
        try:
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text(blob, encoding="utf-8")
            try:
                os.chmod(other, 0o664)
            except OSError:
                pass
        except OSError:
            pass
        return payload
    except OSError:
        return None


_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_FILE_RE = re.compile(r"^[a-zA-Z0-9._-]+\.(png|jpg|jpeg|webp)$", re.I)


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


def _safe_public_url(item: dict) -> str:
    """Absolute public URL for a gallery item, or '' if path looks unsafe."""
    file = str(item.get("file") or "")
    url = str(item.get("url") or "")
    if not url and file:
        url = f"gallery/{file}"
    if not url or ".." in url or "\\" in url or url.startswith("/"):
        return ""
    if url.startswith("gallery/"):
        rest = url[len("gallery/") :]
        if not _FILE_RE.match(rest):
            return ""
        return f"{PUBLIC_BASE}/{url}"
    # Root-level seeds on the product page (e.g. lighthouse.png).
    if _FILE_RE.match(url) and "/" not in url:
        return f"{PUBLIC_BASE}/{url}"
    return ""


def _enrich_item(item: dict) -> dict:
    out = dict(item)
    out["hidden"] = bool(item.get("hidden"))
    out["pinned"] = bool(item.get("pinned")) or str(item.get("id") or "") == "lighthouse"
    out["public_url"] = _safe_public_url(item)
    out["in_gallery"] = not out["hidden"]
    prompt = str(out.get("prompt") or "")
    if len(prompt) > 140:
        out["prompt_short"] = prompt[:137] + "..."
    else:
        out["prompt_short"] = prompt
    return out


def _read_manifest_unlocked(fh) -> dict:
    raw = fh.read()
    if not raw or not raw.strip():
        return {"items": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"items": []}
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def load_gallery_items() -> list[dict]:
    """All manifest items (including hidden), newest first as stored."""
    if not GALLERY_MANIFEST.is_file():
        return []
    try:
        with GALLERY_MANIFEST.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                data = _read_manifest_unlocked(fh)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        return []
    items = []
    for it in data.get("items") or []:
        if isinstance(it, dict) and it.get("id"):
            items.append(_enrich_item(it))
    return items


def set_gallery_hidden(item_id: str, hidden: bool) -> dict:
    """Set or clear the ``hidden`` flag on a gallery item. Returns the updated item.

    When an item transitions to hidden, its ``cost_usd`` is subtracted from the
    public spend tally (and image_count decremented). Un-hiding adds it back.
    """
    item_id = (item_id or "").strip()
    if not item_id or not _ID_RE.match(item_id):
        raise ValueError("Invalid gallery item id")

    if not GALLERY_MANIFEST.is_file():
        raise FileNotFoundError(f"Gallery manifest not found: {GALLERY_MANIFEST}")

    with GALLERY_MANIFEST.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_manifest_unlocked(fh)
            items = data.get("items") or []
            found = None
            was_hidden = False
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("id") or "") == item_id:
                    was_hidden = bool(it.get("hidden"))
                    if hidden:
                        it["hidden"] = True
                    else:
                        it.pop("hidden", None)
                    found = it
                    break
            if found is None:
                raise KeyError(f"No gallery item with id {item_id!r}")
            data["items"] = items
            data["updated_at"] = int(time.time())
            payload = json.dumps(data, ensure_ascii=False, indent=4) + "\n"
            fh.seek(0)
            fh.truncate()
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())

            # Adjust spend only on a real visibility transition.
            if was_hidden != bool(hidden):
                cost = _item_cost_usd(found)
                if cost > 0 and not found.get("pinned"):
                    adjust_spend_for_visibility(cost, becoming_hidden=bool(hidden))

            return _enrich_item(found)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def gallery_stats() -> dict:
    items = load_gallery_items()
    visible = sum(1 for i in items if not i.get("hidden"))
    return {
        "gallery_items": items,
        "gallery_total": len(items),
        "gallery_visible": visible,
        "gallery_hidden": len(items) - visible,
        "gallery_manifest": str(GALLERY_MANIFEST),
        "public_base": PUBLIC_BASE,
    }


def stats() -> dict:
    """Aggregate trial log + gallery for the dashboard panel."""
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
    out = {
        "path": str(TRIALS_PATH),
        "total_attempts": len(tries),
        "successes": len(ok),
        "failures": len(fail),
        "unique_emails": len(emails),
        "honeypots": sum(1 for e in events if e.get("event") == "honeypot"),
        "recent": recent,
        "error": None,
    }
    try:
        out.update(gallery_stats())
    except Exception as e:
        out["gallery_items"] = []
        out["gallery_total"] = 0
        out["gallery_visible"] = 0
        out["gallery_hidden"] = 0
        out["gallery_manifest"] = str(GALLERY_MANIFEST)
        out["public_base"] = PUBLIC_BASE
        out["gallery_error"] = str(e)
    return out
