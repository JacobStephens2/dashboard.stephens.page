from . import Account, Signup, Health, Storage
from ._helpers import fetch_mysql, app_root, dir_bytes

NAME = 'gameplan'
LABEL = 'GamePlan'
ACTIVITY = 'players entered'


async def accounts() -> list[Account]:
    rows = await fetch_mysql(NAME, """
        SELECT u.email, u.trn_date AS created_at,
               COUNT(DISTINCT p.id) AS player_count
        FROM users u
        LEFT JOIN players p ON p.user_id = u.id
        GROUP BY u.id
        ORDER BY player_count DESC, u.id DESC
    """)
    return [
        Account(app=LABEL, email=r['email'],
                created_at=str(r['created_at']) if r['created_at'] else None,
                activity_label=ACTIVITY,
                extra={'player_count': r['player_count']})
        for r in rows
    ]


async def recent_signups(limit: int = 50) -> list[Signup]:
    rows = await fetch_mysql(NAME,
        "SELECT email, trn_date AS created_at FROM users ORDER BY trn_date DESC LIMIT %s", (limit,))
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
