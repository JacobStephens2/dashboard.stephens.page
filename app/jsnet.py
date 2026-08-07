"""Publishing control for jacobstephens.net.

That site keeps its publishing state in posts.json and rewrites itself with
tools/publish.py: the script owns both archive listings and the `noindex` tag
on each post. This module drives the script rather than editing HTML, so the
dashboard and the command line cannot drift apart. Contrast blog.py, which
parses stephens.page's archive with regexes because that site has no manifest.

One difference matters more than the rest. The stephens.page checkout is a
source tree; this checkout *is* the live site. Publishing here takes effect
the moment the script runs, with no deploy step in between. So each change is
committed and pushed immediately, which keeps history linear and leaves the
tree clean for the next `git pull`. A dirty tree is the one thing that breaks
that deploy path, so a dirty tree is also the one thing that stops us early.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import JSNET_SITE_DIR, JSNET_SITE_URL

SITE_DIR = Path(JSNET_SITE_DIR)
SITE_URL = JSNET_SITE_URL.rstrip("/")
MANIFEST = SITE_DIR / "posts.json"
PUBLISH_PY = SITE_DIR / "tools" / "publish.py"

# Drafts sit behind one shared password. This path must match DRAFT_HTPASSWD in
# the site's tools/publish.py, which writes the .htaccess pointing at it. It is
# deliberately outside the site repository: that repo is public, so the hash
# cannot live there, and outside any document root, so it is never served.
DRAFT_HTPASSWD = Path("/var/www/.htpasswd-drafts")
DRAFT_USER = "preview"
MIN_PASSWORD = 10

# Long enough for a slow push, short enough that a hung credential prompt
# surfaces as an error instead of pinning a worker thread.
_TIMEOUT = 60


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    # Never let git stop for a username: fail loudly instead of hanging.
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(args: list[str], *, what: str) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=str(SITE_DIR),
            env=_git_env(),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{what} timed out after {_TIMEOUT}s")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(f"{what} failed: {detail[-1] if detail else 'no output'}")
    return proc.stdout


def _dirty_paths() -> list[str]:
    out = _run(["git", "status", "--porcelain"], what="git status")
    return [line[3:] for line in out.splitlines() if line.strip()]


def _parse_date(value: str) -> float:
    for fmt in ("%B %d, %Y", "%B %Y", "%Y"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def _read_manifest() -> dict:
    if not MANIFEST.exists():
        raise RuntimeError(f"No posts.json at {MANIFEST}")
    return json.loads(MANIFEST.read_text())


def load_posts() -> list[dict]:
    """Every post in the manifest, drafts first so they are what you see."""
    data = _read_manifest()
    posts = []
    for entry in data.get("posts", []):
        slug = entry.get("slug", "")
        if not slug:
            continue
        published = entry.get("status") == "published"
        posts.append(
            {
                "slug": slug,
                "title": entry.get("title", slug),
                "date_text": entry.get("date", ""),
                "categories": entry.get("categories", []),
                "published": published,
                "url": f"{SITE_URL}/posts/{slug}/",
                "sort_ts": _parse_date(entry.get("date", "")),
            }
        )
    # Drafts first: they are the ones awaiting a decision. Then newest first.
    posts.sort(key=lambda p: (p["published"], -p["sort_ts"], p["slug"]))
    return posts


def site_state() -> dict:
    """Whether the checkout is safe to act on, for display and for guarding."""
    try:
        dirty = _dirty_paths()
    except RuntimeError as e:
        return {"ok": False, "dirty": [], "reason": str(e)}
    if dirty:
        return {
            "ok": False,
            "dirty": dirty,
            "reason": (
                "The site checkout has uncommitted changes. Publishing would "
                "sweep them into its commit, so it is blocked until they are "
                "committed or reverted."
            ),
        }
    return {"ok": True, "dirty": [], "reason": ""}


def preview_password_set() -> bool:
    """Whether a draft preview password exists. Never reveals the hash."""
    try:
        return DRAFT_HTPASSWD.is_file() and DRAFT_HTPASSWD.stat().st_size > 0
    except OSError:
        return False


def set_preview_password(password: str) -> None:
    """Write the shared draft password.

    Handed to htpasswd on stdin rather than argv, so it never shows up in the
    process list. Nothing here logs or returns it.
    """
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters.")

    try:
        proc = subprocess.run(
            ["htpasswd", "-i", "-c", str(DRAFT_HTPASSWD), DRAFT_USER],
            input=password,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        raise RuntimeError("htpasswd is not installed on this server.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("htpasswd timed out.")
    if proc.returncode != 0:
        # stderr can echo the input; report the status only.
        raise RuntimeError(f"htpasswd failed (exit {proc.returncode}).")

    # Apache runs as another user and must read it. The file holds a hash, not
    # the password, and sits outside every document root.
    os.chmod(DRAFT_HTPASSWD, 0o644)


def set_published(slug: str, published: bool) -> list[dict]:
    """Flip one post's status, then commit and push the result.

    Refuses on a dirty tree: `git add -A` after the rewrite would otherwise
    capture unrelated edits, and an unexpected diff is exactly the signal that
    something else is going on in the checkout.
    """
    slug = slug.strip()
    posts = load_posts()
    target = next((p for p in posts if p["slug"] == slug), None)
    if target is None:
        raise ValueError(f"Unknown post slug: {slug}")
    if target["published"] == published:
        raise ValueError(
            f"{slug} is already {'published' if published else 'a draft'}."
        )

    state = site_state()
    if not state["ok"]:
        raise RuntimeError(state["reason"])

    if not PUBLISH_PY.exists():
        raise RuntimeError(f"No publish script at {PUBLISH_PY}")

    action = "publish" if published else "draft"
    _run([sys.executable, str(PUBLISH_PY), action, slug], what=f"publish.py {action}")

    # The script owns two views of the site; make it prove they agree before
    # any of it is committed.
    _run([sys.executable, str(PUBLISH_PY), "check"], what="publish.py check")

    changed = _dirty_paths()
    if not changed:
        # Status flipped in the manifest but nothing on disk moved: the site
        # was already in the target shape. Nothing to commit.
        return load_posts()

    verb = "Publish" if published else "Unpublish"
    message = f"{verb} the post “{target['title']}”.\n\nvia the dashboard"
    _run(["git", "add", "-A"], what="git add")
    _run(["git", "commit", "-m", message], what="git commit")
    _run(["git", "push", "origin", "HEAD"], what="git push")

    return load_posts()
