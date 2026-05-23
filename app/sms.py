"""SMS alert delivery.

Pluggable provider behind a single async function:

    await send_alert_sms(name, direction, detail)

The provider is chosen at runtime via the SMS_PROVIDER env var:

    SMS_PROVIDER=none      (default — silent no-op)
    SMS_PROVIDER=textbelt  (bridge while 10DLC is pending)
    SMS_PROVIDER=telnyx    (production, post-10DLC approval)

ALERT_PHONE_NUMBER must be set in E.164 format (e.g. "+15551234567"). If it
is empty, the function is a no-op regardless of provider — this lets the
dashboard run safely before any creds are configured.

Provider-specific env vars:
    Textbelt: TEXTBELT_API_KEY
    Telnyx:   TELNYX_API_KEY, TELNYX_FROM_NUMBER
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from . import config  # noqa: F401 — load .env into os.environ

log = logging.getLogger('sms')

SMS_PROVIDER       = os.environ.get('SMS_PROVIDER', 'none').strip().lower()
ALERT_PHONE_NUMBER = os.environ.get('ALERT_PHONE_NUMBER', '').strip()

TEXTBELT_API_KEY   = os.environ.get('TEXTBELT_API_KEY', '').strip()
TELNYX_API_KEY     = os.environ.get('TELNYX_API_KEY', '').strip()
TELNYX_FROM_NUMBER = os.environ.get('TELNYX_FROM_NUMBER', '').strip()


def _format_body(name: str, direction: str, detail: str) -> str:
    """Compact one-line message that fits in a single SMS segment (160 chars)."""
    if direction == 'down':
        body = f'[stephens.page] DOWN: {name} — {detail}'
    else:
        body = f'[stephens.page] RECOVERED: {name}'
    return body[:160]


async def _send_textbelt(body: str) -> None:
    if not TEXTBELT_API_KEY:
        log.warning('SMS_PROVIDER=textbelt but TEXTBELT_API_KEY not set — skipping')
        return
    payload = {
        'phone':   ALERT_PHONE_NUMBER,
        'message': body,
        'key':     TEXTBELT_API_KEY,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post('https://textbelt.com/text', data=payload)
    try:
        data = r.json()
    except Exception:
        data = {'raw': r.text}
    if not data.get('success'):
        log.error('Textbelt send failed: status=%s data=%s', r.status_code, data)
    else:
        log.info('Textbelt sent; quotaRemaining=%s', data.get('quotaRemaining'))


async def _send_telnyx(body: str) -> None:
    if not TELNYX_API_KEY or not TELNYX_FROM_NUMBER:
        log.warning('SMS_PROVIDER=telnyx but TELNYX_API_KEY/TELNYX_FROM_NUMBER not set — skipping')
        return
    payload = {
        'from': TELNYX_FROM_NUMBER,
        'to':   ALERT_PHONE_NUMBER,
        'text': body,
    }
    headers = {
        'Authorization': f'Bearer {TELNYX_API_KEY}',
        'Content-Type':  'application/json',
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post('https://api.telnyx.com/v2/messages',
                              json=payload, headers=headers)
    if r.status_code >= 400:
        log.error('Telnyx send failed: status=%s body=%s', r.status_code, r.text[:300])
    else:
        log.info('Telnyx sent; status=%s', r.status_code)


async def send_alert_sms(name: str, direction: str, detail: str) -> None:
    """Send an SMS alert. No-op if SMS_PROVIDER is 'none' or
    ALERT_PHONE_NUMBER is unset. Logs and swallows provider errors so a
    failed SMS never blocks the email path."""
    if SMS_PROVIDER == 'none' or not SMS_PROVIDER:
        return
    if not ALERT_PHONE_NUMBER:
        log.warning('SMS_PROVIDER=%s but ALERT_PHONE_NUMBER not set — skipping', SMS_PROVIDER)
        return

    body = _format_body(name, direction, detail)
    try:
        if SMS_PROVIDER == 'textbelt':
            await _send_textbelt(body)
        elif SMS_PROVIDER == 'telnyx':
            await _send_telnyx(body)
        else:
            log.error('Unknown SMS_PROVIDER=%s — skipping', SMS_PROVIDER)
    except Exception:
        log.exception('SMS send raised (provider=%s)', SMS_PROVIDER)
