from . import Account, Signup, Health, Storage
from ._helpers import fetch_mysql, app_root, dir_bytes, systemctl_active, systemd_unit

NAME = 'exodus'
LABEL = 'Exodus 40 Lite'
ACTIVITY = 'last data update'


async def accounts() -> list[Account]:
    rows = await fetch_mysql(NAME, """
        SELECT u.username AS email, u.created_at,
               FROM_UNIXTIME(MAX(ud.updated_at)/1000) AS last_activity
        FROM users u
        LEFT JOIN user_data ud ON ud.user_id = u.id
        GROUP BY u.id
        ORDER BY last_activity DESC
    """)
    return [
        Account(app=LABEL, email=r['email'],
                created_at=str(r['created_at']) if r['created_at'] else None,
                last_activity=str(r['last_activity']) if r['last_activity'] else None,
                activity_label=ACTIVITY)
        for r in rows
    ]


async def recent_signups(limit: int = 50) -> list[Signup]:
    rows = await fetch_mysql(NAME,
        "SELECT username AS email, created_at FROM users ORDER BY created_at DESC LIMIT %s", (limit,))
    return [Signup(app=LABEL, email=r['email'],
                   created_at=str(r['created_at']) if r['created_at'] else None) for r in rows]


async def health() -> Health:
    try:
        await fetch_mysql(NAME, "SELECT 1")
        return Health(app=LABEL, db_reachable=True)
    except Exception as e:
        return Health(app=LABEL, db_reachable=False, db_error=str(e))


async def storage() -> Storage:
    try:
        cnt = (await fetch_mysql(NAME, "SELECT COUNT(*) AS n FROM users"))[0]['n']
    except Exception:
        cnt = None
    return Storage(app=LABEL, app_dir_bytes=dir_bytes(app_root(NAME)), user_count=cnt)
