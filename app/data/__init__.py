"""Per-app data adapters.

Each adapter module exposes a few async functions:
- accounts() -> list[Account]
- recent_signups(since: datetime | None = None) -> list[Signup]
- health() -> Health
- storage() -> Storage
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Account:
    app: str
    email: str
    name: Optional[str] = None
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    activity_label: Optional[str] = None  # what "activity" means in this app
    extra: dict = field(default_factory=dict)


@dataclass
class Signup:
    app: str
    email: str
    created_at: Optional[str]


@dataclass
class Health:
    app: str
    # True = reachable, False = unreachable, None = no database (e.g. client-only app)
    db_reachable: Optional[bool]
    db_error: Optional[str] = None
    service_unit: Optional[str] = None
    service_active: Optional[bool] = None
    note: Optional[str] = None  # free-form context, e.g. "static site, no backend"


@dataclass
class Storage:
    app: str
    app_dir_bytes: int = 0
    db_bytes: int = 0
    user_count: Optional[int] = None
