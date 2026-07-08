"""Uptime monitoring + alerting.

Defines a list of `Check`s (HTTP URLs + systemd units), runs them on an
interval, and emails jacob@stephens.page when a check transitions from
up→down or down→up. State is persisted in data/uptime.db so a dashboard
restart doesn't trigger a wave of false alerts.

Edit the CHECKS list below to add or remove monitored endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx

from . import config  # noqa: F401 — imported for side effect: loads .env into os.environ
from .sms import send_alert_sms

log = logging.getLogger('uptime')

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / 'data' / 'uptime.db'

CHECK_INTERVAL_SECONDS = int(os.environ.get('UPTIME_INTERVAL', '300'))    # 5 min
FAILURES_BEFORE_ALERT  = int(os.environ.get('UPTIME_FAIL_THRESHOLD', '2'))
ADMIN_EMAIL            = os.environ.get('ADMIN_EMAIL', 'jacob@stephens.page')
RESEND_API_KEY         = os.environ.get('RESEND_API_KEY', '')
MAIL_FROM_EMAIL        = os.environ.get('MAIL_FROM_EMAIL', 'jacob@stephens.page')
MAIL_FROM_NAME         = os.environ.get('MAIL_FROM_NAME', 'Stephens.page Dashboard')


# --- Check definitions --------------------------------------------------------

@dataclass
class Check:
    name: str            # human label
    kind: str            # 'http' | 'systemd'
    target: str          # URL for http, unit name for systemd
    expect_substring: Optional[str] = None   # http only: must appear in body
    timeout: float = 10.0


# Public sites + APIs. Each tuple is (name, url, optional body-substring).
HTTP_CHECKS: list[Check] = [
    Check('15east',                  'http', 'https://15east.stephens.page/'),
    Check('Artifact (web)',          'http', 'https://artifact.stephens.page/'),
    Check('Artifact (api)',          'http', 'https://api.artifact.stephens.page/'),
    Check('blog',                    'http', 'https://blog.stephens.page/'),
    Check('Clowder & Crest',         'http', 'https://clowder.stephens.page/'),
    Check('Drome',                   'http', 'https://drome.day/'),
    Check('coachscall.org',          'http', 'https://coachscall.org/'),
    Check('Chart35',                 'http', 'https://creighton.stephens.page/'),
    Check('creightontracker.com',    'http', 'https://creightontracker.com/'),
    Check('Daily Dozen Tracker',     'http', 'https://dailydozen.stephens.page/'),
    Check('dana4wvt',                'http', 'https://dana4wvt.stephens.page/'),
    Check('drfamiglio.com',          'http', 'https://drfamiglio.com/'),
    Check('Event Manager',           'http', 'https://event.stephens.page/'),
    Check('Event Manager (api)',     'http', 'https://api.event.stephens.page/'),
    Check('Exodus 40 Lite',          'http', 'https://exodus.stephens.page/'),
    Check('GamePlan',                'http', 'https://gameplan.stephens.page/'),
    Check('jackpot',                 'http', 'https://jackpot.stephens.page/'),
    Check('Macros',                  'http', 'https://macros.stephens.page/'),
    Check('magisterium',             'http', 'https://magisterium.stephens.page/'),
    Check('poker',                   'http', 'https://poker.stephens.page/'),
    Check('resume',                  'http', 'https://resume.stephens.page/'),
    Check('stephens.page',           'http', 'https://stephens.page/'),
    Check('Wadadli Flare Catering',  'http', 'https://wadadliflarecatering.com/'),
    Check('wedding',                 'http', 'https://wedding.stephens.page/'),
    Check('wiki',                    'http', 'https://wiki.stephens.page/'),
    Check('dashboard (self)',        'http', 'https://dashboard.stephens.page/login'),
]

SYSTEMD_CHECKS: list[Check] = [
    Check('apache2',         'systemd', 'apache2'),
    Check('mysql',           'systemd', 'mysql'),
    Check('creighton-api',   'systemd', 'creighton-api'),
    Check('macros-api',      'systemd', 'macros-api'),
    Check('dailydozen-api',  'systemd', 'dailydozen-api'),
    Check('dashboard (svc)', 'systemd', 'dashboard'),
]

CHECKS: list[Check] = HTTP_CHECKS + SYSTEMD_CHECKS


# --- State store --------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS check_state (
    name                  TEXT PRIMARY KEY,
    status                TEXT NOT NULL,            -- 'up' | 'down' | 'unknown'
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    last_checked          TEXT,
    last_status_change    TEXT,
    last_error            TEXT
);
CREATE TABLE IF NOT EXISTS alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    direction   TEXT NOT NULL,                      -- 'down' | 'up'
    sent_at     TEXT NOT NULL,
    detail      TEXT
);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


# --- Check runners ------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str   # short human-readable status (e.g. "200 OK", "timeout", "exit code 3")


async def run_http_check(check: Check, client: httpx.AsyncClient) -> CheckResult:
    try:
        resp = await client.get(check.target, timeout=check.timeout, follow_redirects=True)
        if resp.status_code >= 400:
            return CheckResult(check.name, False, f"HTTP {resp.status_code}")
        if check.expect_substring and check.expect_substring not in resp.text:
            return CheckResult(check.name, False, "expected substring missing")
        return CheckResult(check.name, True, f"HTTP {resp.status_code}")
    except httpx.TimeoutException:
        return CheckResult(check.name, False, "timeout")
    except httpx.RequestError as e:
        return CheckResult(check.name, False, f"{type(e).__name__}: {e}"[:200])


async def run_systemd_check(check: Check) -> CheckResult:
    proc = await asyncio.create_subprocess_exec(
        'systemctl', 'is-active', check.target,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    state = stdout.decode().strip()
    ok = state == 'active'
    return CheckResult(check.name, ok, state or 'unknown')


async def run_all_checks() -> list[CheckResult]:
    async with httpx.AsyncClient(headers={'User-Agent': 'stephens-page-uptime/1.0'}) as client:
        coros = []
        for c in CHECKS:
            if c.kind == 'http':
                coros.append(run_http_check(c, client))
            elif c.kind == 'systemd':
                coros.append(run_systemd_check(c))
        results = await asyncio.gather(*coros, return_exceptions=True)
    # Coerce exceptions into failed CheckResults
    out: list[CheckResult] = []
    for c, r in zip(CHECKS, results):
        if isinstance(r, Exception):
            out.append(CheckResult(c.name, False, f"check error: {type(r).__name__}: {r}"[:200]))
        else:
            out.append(r)
    return out


# --- Decision + persistence ---------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


async def update_state_and_decide(result: CheckResult) -> Optional[str]:
    """Update the persisted state for a check and decide whether to send an
    alert. Returns 'down' / 'up' / None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT status, consecutive_failures FROM check_state WHERE name = ?",
            (result.name,)
        )).fetchone()
        prev_status = row['status'] if row else 'unknown'
        prev_fails  = row['consecutive_failures'] if row else 0

        ts = now_iso()
        alert: Optional[str] = None

        if result.ok:
            new_status = 'up'
            new_fails  = 0
            if prev_status == 'down':
                alert = 'up'
        else:
            new_fails = prev_fails + 1
            if new_fails >= FAILURES_BEFORE_ALERT:
                new_status = 'down'
                if prev_status != 'down':
                    alert = 'down'
            else:
                new_status = prev_status if prev_status in ('up', 'down') else 'unknown'

        status_changed = new_status != prev_status

        await db.execute("""
            INSERT INTO check_state(name, status, consecutive_failures, last_checked, last_status_change, last_error)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                status = excluded.status,
                consecutive_failures = excluded.consecutive_failures,
                last_checked = excluded.last_checked,
                last_status_change = CASE WHEN ? THEN excluded.last_status_change ELSE check_state.last_status_change END,
                last_error = excluded.last_error
        """, (result.name, new_status, new_fails, ts, ts, None if result.ok else result.detail, status_changed))
        await db.commit()

    return alert


async def log_alert(name: str, direction: str, detail: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO alert_log(name, direction, sent_at, detail) VALUES (?, ?, ?, ?)",
            (name, direction, now_iso(), detail),
        )
        await db.commit()


# --- Email --------------------------------------------------------------------

async def send_alert_email(name: str, direction: str, detail: str):
    if not RESEND_API_KEY:
        log.warning('RESEND_API_KEY not set — would have alerted %s %s', name, direction)
        return
    subject = (
        f'[stephens.page] DOWN: {name}' if direction == 'down'
        else f'[stephens.page] RECOVERED: {name}'
    )
    body = (
        f"Check: {name}\n"
        f"Status: {direction.upper()}\n"
        f"Detail: {detail}\n"
        f"Time:   {now_iso()} UTC\n"
        f"\n"
        f"Dashboard: https://dashboard.stephens.page/\n"
    )
    payload = {
        'from': f'{MAIL_FROM_NAME} <{MAIL_FROM_EMAIL}>',
        'to': [ADMIN_EMAIL],
        'subject': subject,
        'text': body,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {RESEND_API_KEY}'},
                json=payload,
            )
            r.raise_for_status()
    except Exception as e:
        log.error('Failed to send alert email for %s (%s): %s', name, direction, e)


# --- Scheduler loop -----------------------------------------------------------

async def run_once():
    results = await run_all_checks()
    for res in results:
        alert = await update_state_and_decide(res)
        if alert:
            # Email and SMS in parallel: a slow/failing SMS provider must not
            # delay (or block) the email path, and vice versa.
            await asyncio.gather(
                send_alert_email(res.name, alert, res.detail),
                send_alert_sms(res.name, alert, res.detail),
                return_exceptions=True,
            )
            await log_alert(res.name, alert, res.detail)


async def loop():
    await init_db()
    log.info('Uptime monitor starting; interval=%ds, threshold=%d',
             CHECK_INTERVAL_SECONDS, FAILURES_BEFORE_ALERT)
    while True:
        start = time.monotonic()
        try:
            await run_once()
        except Exception:
            log.exception('Uptime tick raised; continuing')
        elapsed = time.monotonic() - start
        await asyncio.sleep(max(1, CHECK_INTERVAL_SECONDS - elapsed))


# --- API helpers (for dashboard tab) ------------------------------------------

async def all_state() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute("""
            SELECT name, status, consecutive_failures, last_checked, last_status_change, last_error
            FROM check_state ORDER BY (status = 'down') DESC, name
        """)).fetchall()
        return [dict(r) for r in rows]


async def recent_alerts(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT name, direction, sent_at, detail FROM alert_log ORDER BY id DESC LIMIT ?",
            (limit,)
        )).fetchall()
        return [dict(r) for r in rows]
