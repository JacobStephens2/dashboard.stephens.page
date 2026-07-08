import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

ADMIN_PASSWORD_HASH = os.environ['ADMIN_PASSWORD_HASH']
SESSION_SECRET = os.environ['SESSION_SECRET']

# WebAuthn / passkeys. rp_id is the registrable domain so one passkey works across
# every *.stephens.page subdomain (dashboard, server, and the gated tools view).
PASSKEY_RP_ID = os.environ.get('PASSKEY_RP_ID', 'stephens.page')
PASSKEY_RP_NAME = os.environ.get('PASSKEY_RP_NAME', 'Stephens.page Dashboard')
PASSKEY_ORIGINS = set(
    o.strip() for o in os.environ.get(
        'PASSKEY_ORIGINS',
        'https://dashboard.stephens.page,https://server.stephens.page',
    ).split(',') if o.strip()
)
PASSKEY_FILE = os.environ.get('PASSKEY_FILE', str(BASE_DIR / 'data' / 'passkeys.json'))

# TOTP (authenticator-app 2FA) secret for the password login.
TOTP_FILE = os.environ.get('TOTP_FILE', str(BASE_DIR / 'data' / 'totp.json'))

# Bearer token that lets an authorized AI agent / automation read /tools (the private
# tools view). Empty string disables token access (session-only). Set in .env.
TOOLS_FEED_TOKEN = os.environ.get('TOOLS_FEED_TOKEN', '')

# Newsletter service (Rust/Axum) admin API. Same box, so we call it over localhost.
NEWSLETTER_ADMIN_URL = os.environ.get('NEWSLETTER_ADMIN_URL', 'http://127.0.0.1:3462')
NEWSLETTER_ADMIN_TOKEN = os.environ.get('NEWSLETTER_ADMIN_TOKEN', '')

# SQLite paths
SQLITE_DBS = {
    'creighton':  os.environ.get('CREIGHTON_DB',  '/var/www/creighton.stephens.page/server/data/creighton.db'),
    'macros':     os.environ.get('MACROS_DB',     '/var/www/macros.stephens.page/server/data/macros.db'),
    'dailydozen': os.environ.get('DAILYDOZEN_DB', '/var/www/dailydozen.stephens.page/data/daily_dozen.db'),
}

# MySQL credentials per app
def _mysql(prefix: str) -> dict:
    return {
        'host':     os.environ[f'{prefix}_DB_HOST'],
        'user':     os.environ[f'{prefix}_DB_USER'],
        'password': os.environ[f'{prefix}_DB_PASS'],
        'db':       os.environ[f'{prefix}_DB_NAME'],
    }

MYSQL_DBS = {
    'artifact': _mysql('ARTIFACT'),
    'exodus':   _mysql('EXODUS'),
    'gameplan': _mysql('GAMEPLAN'),
    'event':    _mysql('EVENT'),
    'skylar':   _mysql('SKYLAR'),
}

APP_ROOTS = {
    'artifact':   '/var/www/artifact.stephens.page',
    'exodus':     '/var/www/exodus.stephens.page',
    'creighton':  '/var/www/creighton.stephens.page',
    'macros':     '/var/www/macros.stephens.page',
    'dailydozen': '/var/www/dailydozen.stephens.page',
    'gameplan':   '/var/www/gameplan.stephens.page',
    'event':      '/var/www/event.stephens.page',
    'skylar':     '/var/www/skylar.stephens.page',
    'clowder':    '/var/www/clowder.stephens.page',
}

# Map adapter name -> systemd unit (None if no service / Apache-only PHP)
SYSTEMD_UNITS = {
    'creighton':  'chart35-api',
    'macros':     'macros-api',
    'dailydozen': 'dailydozen-api',
}

CACHE_TTL_SECONDS = 60
