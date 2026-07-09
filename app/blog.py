from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

from .config import STEPHENS_BLOG_DIR, STEPHENS_BLOG_INDEX

BLOG_DIR = Path(STEPHENS_BLOG_DIR)
BLOG_INDEX = Path(STEPHENS_BLOG_INDEX)

_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="(.*?)"', re.IGNORECASE | re.DOTALL)
_EYEBROW_RE = re.compile(r'<div class="eyebrow">(.*?)</div>', re.IGNORECASE | re.DOTALL)
_META_DATE_RE = re.compile(r'<p class="meta"><strong>(.*?)</strong>', re.IGNORECASE | re.DOTALL)
_LIST_ITEM_RE = re.compile(
    r'<li>\s*<a href="/blog/([a-z0-9-]+)/">\s*'
    r'<div class="note-meta">(.*?)</div>\s*'
    r'<div class="note-title">(.*?)</div>\s*'
    r'<p class="note-summary">(.*?)</p>\s*'
    r'</a>\s*</li>',
    re.IGNORECASE | re.DOTALL,
)
_NOTES_LIST_RE = re.compile(r'<ul class="notes-list">.*?</ul>', re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", html.unescape(text.replace("&#183;", "&middot;"))).strip()


def _slug_ok(slug: str) -> bool:
    return bool(slug) and all(ch.islower() or ch.isdigit() or ch == "-" for ch in slug)


def _split_parts(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"&middot;|·", text) if part.strip()]


def _parse_date(value: str | None) -> tuple[dt.datetime | None, str | None]:
    if not value:
        return None, None
    text = _clean(value)
    for fmt in ("%B %d, %Y", "%B %Y", "%Y"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed, text
        except ValueError:
            continue
    return None, text


def _load_existing_cards() -> tuple[dict[str, dict], list[str]]:
    if not BLOG_INDEX.exists():
        return {}, []
    text = BLOG_INDEX.read_text()
    cards: dict[str, dict] = {}
    order: list[str] = []
    for match in _LIST_ITEM_RE.finditer(text):
        slug = match.group(1)
        order.append(slug)
        cards[slug] = {
            "note_meta": _clean(match.group(2)),
            "summary": _clean(match.group(4)),
        }
    return cards, order


def _derive_note_meta(date_text: str | None, eyebrow: str) -> str:
    parts = _split_parts(eyebrow)
    if not parts and date_text:
        return date_text
    inferred_date = None
    if parts:
        maybe_date = parts[-1]
        if _parse_date(maybe_date)[0]:
            inferred_date = maybe_date
            parts = parts[:-1]
    display_date = date_text or inferred_date
    if parts and parts[0].lower() == "notes":
        parts = parts[1:]
    pieces = []
    if display_date:
        pieces.append(display_date)
    pieces.extend(parts)
    return " · ".join(piece for piece in pieces if piece)


def _read_post(slug: str, card: dict | None, published_order: dict[str, int]) -> dict | None:
    post_dir = BLOG_DIR / slug
    index_path = post_dir / "index.html"
    if not index_path.is_file():
        return None
    raw = index_path.read_text()
    title_match = _TITLE_RE.search(raw)
    title = _clean(title_match.group(1)) if title_match else slug
    title = re.sub(r"\s*\|\s*Jacob Stephens\s*$", "", title).strip() or slug
    desc_match = _DESC_RE.search(raw)
    description = _clean(desc_match.group(1)) if desc_match else ""
    eyebrow_match = _EYEBROW_RE.search(raw)
    eyebrow = _clean(eyebrow_match.group(1)) if eyebrow_match else ""
    date_match = _META_DATE_RE.search(raw)
    parsed_date, date_text = _parse_date(date_match.group(1) if date_match else None)
    if parsed_date is None and eyebrow:
        parts = _split_parts(eyebrow)
        if parts:
            parsed_date, inferred = _parse_date(parts[-1])
            date_text = date_text or inferred
    note_meta = card["note_meta"] if card else _derive_note_meta(date_text, eyebrow)
    summary = card["summary"] if card else description
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "eyebrow": eyebrow,
        "date_text": date_text or "",
        "note_meta": note_meta,
        "summary": summary,
        "published": slug in published_order,
        "published_rank": published_order.get(slug),
        "sort_ts": parsed_date.timestamp() if parsed_date else 0,
        "path": str(index_path),
    }


def load_posts() -> list[dict]:
    cards, published_order_list = _load_existing_cards()
    published_order = {slug: i for i, slug in enumerate(published_order_list)}
    posts: list[dict] = []
    for child in sorted(BLOG_DIR.iterdir()):
        if not child.is_dir():
            continue
        slug = child.name
        if not _slug_ok(slug):
            continue
        post = _read_post(slug, cards.get(slug), published_order)
        if post:
            posts.append(post)
    posts.sort(
        key=lambda post: (
            0 if post["published"] else 1,
            post["published_rank"] if post["published"] else 0,
            -post["sort_ts"],
            post["slug"],
        )
    )
    return posts


def _render_notes_list(posts: list[dict]) -> str:
    lines = ["                <ul class=\"notes-list\">"]
    for post in posts:
        summary = html.escape(post["summary"], quote=False)
        title = html.escape(post["title"], quote=False)
        note_meta = html.escape(post["note_meta"], quote=False)
        slug = post["slug"]
        lines.extend(
            [
                "                    <li>",
                f"                        <a href=\"/blog/{slug}/\">",
                f"                            <div class=\"note-meta\">{note_meta}</div>",
                f"                            <div class=\"note-title\">{title}</div>",
                f"                            <p class=\"note-summary\">{summary}</p>",
                "                        </a>",
                "                    </li>",
            ]
        )
    lines.append("                </ul>")
    return "\n".join(lines)


def set_published(slug: str, published: bool) -> list[dict]:
    posts = load_posts()
    target = next((post for post in posts if post["slug"] == slug), None)
    if target is None:
        raise ValueError(f"Unknown blog slug: {slug}")

    published_posts = [post for post in posts if post["published"] and post["slug"] != slug]
    if published:
        inserted = False
        for i, post in enumerate(published_posts):
            if target["sort_ts"] > post["sort_ts"]:
                published_posts.insert(i, target)
                inserted = True
                break
        if not inserted:
            published_posts.append(target)

    text = BLOG_INDEX.read_text()
    rendered = _render_notes_list(published_posts)
    updated, count = _NOTES_LIST_RE.subn(rendered, text, count=1)
    if count != 1:
        raise ValueError("Could not locate blog post list in public index.")
    BLOG_INDEX.write_text(updated)
    return load_posts()
