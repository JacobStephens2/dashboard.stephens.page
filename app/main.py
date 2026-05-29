import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    verify_password, issue_session_cookie, clear_session_cookie,
    is_authenticated, require_auth,
)
from .config import CACHE_TTL_SECONDS
from .data import creighton, macros, dailydozen, exodus, artifact, gameplan, event as event_app, skylar, clowder
from . import uptime, system

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / 'app' / 'templates'))

ADAPTERS = [creighton, macros, dailydozen, exodus, artifact, gameplan, event_app, skylar, clowder]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await uptime.init_db()
    task = asyncio.create_task(uptime.loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title='Stephens.page Dashboard', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')


# --- Small in-memory cache (per-section) --------------------------------------

_cache: dict[str, tuple[float, object]] = {}

async def cached(key: str, coro_factory):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    value = await coro_factory()
    _cache[key] = (now, value)
    return value


async def gather_safely(fns):
    """Run coroutines in parallel; on error, swap in the exception so the UI
    can render a degraded row instead of failing the whole page."""
    return await asyncio.gather(*[fn() for fn in fns], return_exceptions=True)


# --- Filters ------------------------------------------------------------------

def humanbytes(n):
    if n is None:
        return '—'
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def humanduration(seconds):
    if seconds is None:
        return '—'
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return ' '.join(parts)


templates.env.filters['humanbytes'] = humanbytes
templates.env.filters['humanduration'] = humanduration


# --- Routes -------------------------------------------------------------------

@app.get('/login', response_class=HTMLResponse)
async def login_form(request: Request, error: str | None = None):
    if is_authenticated(request):
        return RedirectResponse('/', status_code=303)
    return templates.TemplateResponse(request, 'login.html', {'error': error})


@app.post('/login')
async def login_submit(request: Request, password: str = Form(...)):
    if not verify_password(password):
        return RedirectResponse('/login?error=1', status_code=303)
    response = RedirectResponse('/', status_code=303)
    issue_session_cookie(response)
    return response


@app.post('/logout')
async def logout():
    response = RedirectResponse('/login', status_code=303)
    clear_session_cookie(response)
    return response


@app.get('/', response_class=HTMLResponse)
async def home(request: Request, _: None = Depends(require_auth)):
    return templates.TemplateResponse(request, 'dashboard.html')


@app.get('/api/accounts', response_class=HTMLResponse)
async def api_accounts(request: Request, _: None = Depends(require_auth)):
    async def load():
        results = await gather_safely([a.accounts for a in ADAPTERS])
        sections = []
        for adapter, res in zip(ADAPTERS, results):
            sections.append({
                'name': adapter.LABEL,
                'activity_label': getattr(adapter, 'ACTIVITY', None),
                'accounts': [] if isinstance(res, Exception) else res,
                'error': str(res) if isinstance(res, Exception) else None,
            })
        return sections
    sections = await cached('accounts', load)
    return templates.TemplateResponse(request, 'partials/accounts.html', {'sections': sections})


@app.get('/api/signups', response_class=HTMLResponse)
async def api_signups(request: Request, _: None = Depends(require_auth)):
    async def load():
        results = await gather_safely([a.recent_signups for a in ADAPTERS])
        signups = []
        for adapter, res in zip(ADAPTERS, results):
            if isinstance(res, Exception):
                continue
            signups.extend(res)
        signups.sort(key=lambda s: (s.created_at or ''), reverse=True)
        return signups[:50]
    signups = await cached('signups', load)
    return templates.TemplateResponse(request, 'partials/signups.html', {'signups': signups})


@app.get('/api/health', response_class=HTMLResponse)
async def api_health(request: Request, _: None = Depends(require_auth)):
    async def load():
        return await gather_safely([a.health for a in ADAPTERS])
    rows = await cached('health', load)
    # Coerce exceptions into a placeholder row
    safe = []
    for adapter, r in zip(ADAPTERS, rows):
        if isinstance(r, Exception):
            from .data import Health
            safe.append(Health(app=adapter.LABEL, db_reachable=False, db_error=str(r)))
        else:
            safe.append(r)
    return templates.TemplateResponse(request, 'partials/health.html', {'rows': safe})


@app.get('/api/storage', response_class=HTMLResponse)
async def api_storage(request: Request, _: None = Depends(require_auth)):
    async def load():
        return await gather_safely([a.storage for a in ADAPTERS])
    rows = await cached('storage', load)
    safe = []
    for adapter, r in zip(ADAPTERS, rows):
        if isinstance(r, Exception):
            from .data import Storage
            safe.append(Storage(app=adapter.LABEL))
        else:
            safe.append(r)
    return templates.TemplateResponse(request, 'partials/storage.html', {'rows': safe})


@app.get('/api/system', response_class=HTMLResponse)
async def api_system(request: Request, _: None = Depends(require_auth)):
    # Cheap procfs reads; cache briefly so rapid refreshes don't re-stat disks.
    stats = await cached('system', lambda: asyncio.to_thread(system.collect))
    return templates.TemplateResponse(request, 'partials/system.html', {'s': stats})


@app.get('/api/uptime', response_class=HTMLResponse)
async def api_uptime(request: Request, _: None = Depends(require_auth)):
    state = await uptime.all_state()
    alerts = await uptime.recent_alerts(50)
    return templates.TemplateResponse(request, 'partials/uptime.html', {'state': state, 'alerts': alerts})


@app.post('/api/uptime/check-now')
async def api_uptime_check_now(_: None = Depends(require_auth)):
    await uptime.run_once()
    return {'ok': True}


@app.post('/api/refresh')
async def api_refresh(_: None = Depends(require_auth)):
    _cache.clear()
    return {'ok': True}


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    # If require_auth threw a 303, honor it as a redirect
    if exc.status_code == 303 and 'Location' in (exc.headers or {}):
        return RedirectResponse(exc.headers['Location'], status_code=303)
    raise exc
