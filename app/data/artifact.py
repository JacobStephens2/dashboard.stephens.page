from . import Account, Signup, Health, Storage
from ._helpers import fetch_mysql, app_root, dir_bytes

NAME = 'artifact'
LABEL = 'Artifact Manager'
ACTIVITY = 'last "use" entry'


async def accounts() -> list[Account]:
    rows = await fetch_mysql(NAME, """
        SELECT u.email, u.username,
               CONCAT_WS(' ', u.first_name, u.last_name) AS name,
               u.date_created,
               MAX(ut.UseDate) AS last_activity,
               COUNT(ut.ID) AS use_count
        FROM users u
        LEFT JOIN use_table ut ON ut.user_id = u.id
        GROUP BY u.id
        ORDER BY last_activity DESC
    """)
    return [
        Account(app=LABEL, email=r['email'], name=r['name'],
                created_at=str(r['date_created']) if r['date_created'] else None,
                last_activity=str(r['last_activity']) if r['last_activity'] else None,
                activity_label=ACTIVITY,
                extra={'use_count': r['use_count']})
        for r in rows
    ]


async def recent_signups(limit: int = 50) -> list[Signup]:
    rows = await fetch_mysql(NAME,
        "SELECT email, date_created FROM users ORDER BY date_created DESC LIMIT %s", (limit,))
    return [Signup(app=LABEL, email=r['email'],
                   created_at=str(r['date_created']) if r['date_created'] else None) for r in rows]


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
