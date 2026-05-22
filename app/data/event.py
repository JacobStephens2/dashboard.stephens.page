from . import Account, Signup, Health, Storage
from ._helpers import fetch_mysql, app_root, dir_bytes

NAME = 'event'
LABEL = 'Event Manager'
ACTIVITY = 'last event date'


async def accounts() -> list[Account]:
    rows = await fetch_mysql(NAME, """
        SELECT u.email,
               MAX(e.date) AS last_activity,
               COUNT(DISTINCT e.id) AS events,
               COUNT(DISTINCT t.id) AS tasks
        FROM users u
        LEFT JOIN events e ON e.user_id = u.id
        LEFT JOIN tasks t  ON t.user_id = u.id
        GROUP BY u.id
        ORDER BY last_activity DESC
    """)
    return [
        Account(app=LABEL, email=r['email'],
                last_activity=str(r['last_activity']) if r['last_activity'] else None,
                activity_label=ACTIVITY,
                extra={'events': r['events'], 'tasks': r['tasks']})
        for r in rows
    ]


async def recent_signups(limit: int = 50) -> list[Signup]:
    # Event's users table has no created_at column.
    rows = await fetch_mysql(NAME, "SELECT email FROM users ORDER BY id DESC LIMIT %s", (limit,))
    return [Signup(app=LABEL, email=r['email'], created_at=None) for r in rows]


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
