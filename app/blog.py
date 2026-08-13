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
# Swallow the leading indent too. Without this the replacement is inserted after the
# whitespace already on the line, so every publish pushed the list further right.
_NOTES_LIST_RE = re.compile(r'[ \t]*<ul class="notes-list">.*?</ul>', re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
# The tree is live, so an unpublished post is still readable by anyone holding its
# URL. Dropping off the public index hides it from readers; this tag is what keeps
# a draft out of search results until it is published.
_ROBOTS_RE = re.compile(r'[ \t]*<meta\s+name="robots"[^>]*>\n?', re.IGNORECASE)
_ROBOTS_ANCHOR_RE = re.compile(r'<meta\s+charset="[^"]*">', re.IGNORECASE)
_ROBOTS_TAG = '\n    <meta name="robots" content="noindex, nofollow">'


def set_noindex(path: Path, noindex: bool) -> bool:
    """Add or remove the draft ``robots`` tag. Returns True if the file changed."""
    raw = path.read_text()
    updated = _ROBOTS_RE.sub("", raw)
    if noindex:
        anchor = _ROBOTS_ANCHOR_RE.search(updated)
        if anchor is None:
            return False
        updated = updated[: anchor.end()] + _ROBOTS_TAG + updated[anchor.end() :]
    if updated == raw:
        return False
    path.write_text(updated)
    return True


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
            # _clean is for showing the card in the dashboard: entities unescaped,
            # whitespace collapsed. The *_html values are what goes back into the
            # public index verbatim. Round-tripping a card through _clean and then
            # html.escape would turn a live <code> tag in a summary into literal
            # &lt;code&gt; text, so publishing one post would damage the others.
            "note_meta": _clean(match.group(2)),
            "summary": _clean(match.group(4)),
            "note_meta_html": match.group(2).strip(),
            "summary_html": match.group(4).strip(),
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
    # A post with no card yet has never been in the index, so its text comes from the
    # post's own <meta> and must be escaped once, here.
    note_meta_html = card["note_meta_html"] if card else html.escape(note_meta, quote=False)
    summary_html = card["summary_html"] if card else html.escape(summary, quote=False)
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "eyebrow": eyebrow,
        "date_text": date_text or "",
        "note_meta": note_meta,
        "summary": summary,
        "note_meta_html": note_meta_html,
        "summary_html": summary_html,
        "published": slug in published_order,
        "published_rank": published_order.get(slug),
        "noindex": bool(_ROBOTS_RE.search(raw)),
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
    # Newest first, drafts and published interleaved by date - a draft is usually the
    # most recent thing on disk, so this puts what you are working on at the top
    # without a separate section. The Unpublished badge carries the distinction.
    # This is display order only; set_published() re-derives the public index order
    # from published_rank so rewriting it never depends on how this list is sorted.
    posts.sort(key=lambda post: (-post["sort_ts"], post["slug"]))
    return posts


def _render_notes_list(posts: list[dict]) -> str:
    lines = ["                <ul class=\"notes-list\">"]
    for post in posts:
        summary = post["summary_html"]
        title = html.escape(post["title"], quote=False)
        note_meta = post["note_meta_html"]
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
    # Keep the public index in its existing order regardless of display sorting.
    published_posts.sort(key=lambda post: post["published_rank"])
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
    # Index membership and crawlability move together: a draft carries noindex,
    # a published post must not, or publishing would be silently ineffective.
    set_noindex(Path(target["path"]), not published)
    return load_posts()
