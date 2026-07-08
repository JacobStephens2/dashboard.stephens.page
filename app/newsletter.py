"""Client for the Rust newsletter service's token-gated admin API.

The newsletter service (newsletter.stephens.page / 127.0.0.1:3462) owns the
subscriber database. The dashboard never touches that DB directly; it reads and
acts through this admin API. Called over localhost, so plain HTTP is fine.
"""

import httpx

from .config import NEWSLETTER_ADMIN_URL, NEWSLETTER_ADMIN_TOKEN

_HEADERS = {"Authorization": f"Bearer {NEWSLETTER_ADMIN_TOKEN}"}
_TIMEOUT = httpx.Timeout(10.0)


async def fetch() -> dict:
    """Stats + recent subscribers + send history."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{NEWSLETTER_ADMIN_URL}/admin/subscribers", headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def unsubscribe(email: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/unsubscribe",
                         json={"email": email}, headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def delete(email: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/delete",
                         json={"email": email}, headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def send(slug: str, force: bool = False) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/send",
                         json={"slug": slug, "force": force}, headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def compose_seed(slug: str) -> dict:
    """Seed the editor with subject + body built from a published post."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/compose",
                         json={"slug": slug}, headers=_HEADERS)
        return r.json()


async def preview(body_html: str) -> str:
    """Return the composed body wrapped in the full email shell (HTML)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/preview",
                         json={"body_html": body_html}, headers=_HEADERS)
        r.raise_for_status()
        return r.text


async def add(email: str) -> dict:
    """Manually add a subscriber (as confirmed)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/add", json={"email": email}, headers=_HEADERS)
        return r.json()


async def posts() -> list:
    """Published posts available to send: [{slug, title}]."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{NEWSLETTER_ADMIN_URL}/admin/posts", headers=_HEADERS)
        r.raise_for_status()
        return r.json().get("posts", [])


async def sent_html(send_id: int) -> str:
    """The stored HTML of a recorded send."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{NEWSLETTER_ADMIN_URL}/admin/sent", params={"id": send_id}, headers=_HEADERS)
        return r.text


async def send_html(subject: str, body_html: str, test_email: str = "") -> dict:
    """Send a composed email to a test address (if given) or all confirmed subscribers."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{NEWSLETTER_ADMIN_URL}/admin/send_html",
                         json={"subject": subject, "body_html": body_html, "test_email": test_email},
                         headers=_HEADERS)
        return r.json()
