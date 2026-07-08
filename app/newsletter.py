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
