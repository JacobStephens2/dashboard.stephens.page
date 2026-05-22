# stephens.page dashboard

A small admin dashboard that aggregates accounts, recent signups, service
health, and storage usage across the apps running under `/var/www/` on
stephens.page.

Live: <https://dashboard.stephens.page>

## Stack

- **Python 3.12** + **FastAPI** + **Jinja2** templates, served by **uvicorn**
- **HTMX** for tab swaps (no JS toolchain)
- **aiomysql** / **aiosqlite** — fans out async DB queries across 8 apps in
  parallel (`asyncio.gather`)
- 60-second in-memory cache keyed per section

## Layout

```
app/
  config.py           env loading, per-app DB credentials & paths
  auth.py             bcrypt password + itsdangerous signed cookie
  main.py             FastAPI routes, template wiring, parallel fan-out
  data/               one async adapter per app
    creighton.py        Node/SQLite — sync snapshots, systemd unit
    macros.py           Node/SQLite — meal/weight/workout logs
    dailydozen.py       Node/SQLite — daily checklist
    exodus.py           PHP/MySQL — user_data updated_at (ms epoch)
    artifact.py         PHP/MySQL — use_table.UseDate
    gameplan.py         PHP/MySQL — players count
    event.py            PHP/Slim/MySQL — events + tasks
    skylar.py           Laravel/MySQL — users.updated_at
  templates/
    base.html
    login.html
    dashboard.html
    partials/         HTMX fragments (accounts/signups/health/storage)
static/style.css
systemd/dashboard.service
apache/dashboard.stephens.page.conf
```

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # then fill in secrets
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Generate a password hash and session secret:

```bash
.venv/bin/python -c "
import bcrypt, secrets
print('SESSION_SECRET=' + secrets.token_hex(32))
print('ADMIN_PASSWORD_HASH=' + bcrypt.hashpw(b'YOUR-PASSWORD', bcrypt.gensalt()).decode())
"
```

## Deployment

- systemd unit: `/etc/systemd/system/dashboard.service` (uvicorn on
  `127.0.0.1:3460`, restart on failure, `User=jacob`)
- Apache vhost: HTTPS-only via Let's Encrypt, ProxyPass `/` → uvicorn
- `.env` lives outside git, chmod 600

```bash
sudo cp systemd/dashboard.service /etc/systemd/system/
sudo systemctl enable --now dashboard
sudo cp apache/dashboard.stephens.page.conf /etc/apache2/sites-available/
sudo a2ensite dashboard.stephens.page
sudo certbot --apache -d dashboard.stephens.page
```

## Uptime monitoring

A background asyncio task in the same dashboard process runs the checks in
`app/uptime.py` every `UPTIME_INTERVAL` seconds (default 300). Each check is
either:

- `http` — HTTPS GET with a 10 s timeout; any 2xx/3xx is "up"
- `systemd` — `systemctl is-active <unit>`; "active" is "up"

State is persisted in `data/uptime.db`. A check has to fail
`UPTIME_FAIL_THRESHOLD` (default 2) times consecutively before the monitor
sends a DOWN alert to `ADMIN_EMAIL` via Mandrill; a RECOVERED alert fires on
the next successful check. Alerts only fire on transitions — no repeat
emails while a check stays down.

Edit the `HTTP_CHECKS` and `SYSTEMD_CHECKS` lists in `app/uptime.py` to add
or remove monitored endpoints, then `sudo systemctl restart dashboard`.

The "Uptime" tab on the dashboard shows current status per check and the
most recent alerts; a **Check all now** button forces an immediate round
without waiting for the timer.

## Adding a new app

1. Drop a new module in `app/data/your_app.py` exposing `accounts()`,
   `recent_signups()`, `health()`, `storage()` (all async).
2. Add it to the `ADAPTERS` list in `app/main.py`.
3. Add its connection details to `.env` and `app/config.py`.
4. Restart: `sudo systemctl restart dashboard`.

## Notes

- Each section runs all adapters in parallel; an adapter raising an
  exception only degrades its own row, not the whole page.
- SQLite reads open `?mode=ro` URIs to avoid acquiring write locks against
  production DBs.
- DB file size sums `*.db`, `*.db-wal`, and `*.db-shm` (WAL mode is the
  default for several of these apps).
