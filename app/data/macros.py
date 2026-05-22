from . import Account, Signup, Health, Storage
from ._helpers import fetch_sqlite, app_root, dir_bytes, file_bytes, systemctl_active, systemd_unit
from ..config import SQLITE_DBS

NAME = 'macros'
LABEL = 'Macros'
ACTIVITY = 'last log'


async def accounts() -> list[Account]:
    rows = await fetch_sqlite(NAME, """
        SELECT u.email, u.first_name, u.created_at,
               MAX(COALESCE(ml.created_at, wl.created_at, wd.date)) AS last_activity
        FROM users u
        LEFT JOIN meal_logs   ml ON ml.user_id = u.id
        LEFT JOIN weight_logs wl ON wl.user_id = u.id
        LEFT JOIN workout_days wd ON wd.user_id = u.id
        GROUP BY u.id
        ORDER BY last_activity DESC NULLS LAST
    """)
    return [
        Account(app=LABEL, email=r['email'], name=r['first_name'],
                created_at=r['created_at'], last_activity=r['last_activity'],
                activity_label=ACTIVITY)
        for r in rows
    ]


async def recent_signups(limit: int = 50) -> list[Signup]:
    rows = await fetch_sqlite(NAME,
        "SELECT email, created_at FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
    return [Signup(app=LABEL, email=r['email'], created_at=r['created_at']) for r in rows]


async def health() -> Health:
    unit = systemd_unit(NAME)
    try:
        await fetch_sqlite(NAME, "SELECT 1")
        return Health(app=LABEL, db_reachable=True,
                      service_unit=unit, service_active=await systemctl_active(unit))
    except Exception as e:
        return Health(app=LABEL, db_reachable=False, db_error=str(e),
                      service_unit=unit, service_active=await systemctl_active(unit))


async def storage() -> Storage:
    cnt = (await fetch_sqlite(NAME, "SELECT COUNT(*) AS n FROM users"))[0]['n']
    return Storage(app=LABEL,
                   app_dir_bytes=dir_bytes(app_root(NAME)),
                   db_bytes=file_bytes(SQLITE_DBS[NAME]),
                   user_count=cnt)
