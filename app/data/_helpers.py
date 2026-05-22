import asyncio
import os
from pathlib import Path
from typing import Optional

import aiomysql
import aiosqlite

from ..config import APP_ROOTS, SYSTEMD_UNITS, MYSQL_DBS, SQLITE_DBS


async def mysql_conn(app_name: str):
    cfg = MYSQL_DBS[app_name]
    return await aiomysql.connect(
        host=cfg['host'], user=cfg['user'], password=cfg['password'],
        db=cfg['db'], autocommit=True, charset='utf8mb4',
    )


async def fetch_mysql(app_name: str, sql: str, params=()):
    conn = await mysql_conn(app_name)
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())
    finally:
        conn.close()


async def fetch_sqlite(app_name: str, sql: str, params=()):
    path = SQLITE_DBS[app_name]
    async with aiosqlite.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


def dir_bytes(path: str) -> int:
    total = 0
    p = Path(path)
    if not p.exists():
        return 0
    for root, dirs, files in os.walk(p, followlinks=False):
        # skip noise
        dirs[:] = [d for d in dirs if d not in ('node_modules', 'vendor', '.git', '.venv', '__pycache__')]
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def file_bytes(path: str) -> int:
    """Size of a SQLite DB including its WAL/SHM sidecars (if present)."""
    total = 0
    for p in (path, f'{path}-wal', f'{path}-shm'):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


async def systemctl_active(unit: Optional[str]) -> Optional[bool]:
    if not unit:
        return None
    proc = await asyncio.create_subprocess_exec(
        'systemctl', 'is-active', unit,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() == 'active'


def app_root(app_name: str) -> str:
    return APP_ROOTS[app_name]


def systemd_unit(app_name: str) -> Optional[str]:
    return SYSTEMD_UNITS.get(app_name)
