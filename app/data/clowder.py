from . import Account, Signup, Health, Storage
from ._helpers import app_root, dir_bytes

NAME = 'clowder'
LABEL = 'Clowder & Crest'
ACTIVITY = '—'


async def accounts() -> list[Account]:
    return []


async def recent_signups(limit: int = 50) -> list[Signup]:
    return []


async def health() -> Health:
    return Health(app=LABEL, db_reachable=None,
                  note='Phaser/Capacitor game · client-only, no backend')


async def storage() -> Storage:
    return Storage(app=LABEL, app_dir_bytes=dir_bytes(app_root(NAME)))
