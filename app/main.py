import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request, Depends, HTTPException, Body
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    verify_password, issue_session_cookie, clear_session_cookie,
    is_authenticated, require_auth,
)
from . import passkey
from . import totp as totp_mod
from .config import CACHE_TTL_SECONDS, PASSKEY_ORIGINS, TOOLS_FEED_TOKEN
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
    return templates.TemplateResponse(
        request, 'login.html', {'error': error, 'totp_enabled': totp_mod.is_enabled()})


@app.post('/login')
async def login_submit(request: Request, password: str = Form(...), code: str = Form('')):
    if not verify_password(password):
        return RedirectResponse('/login?error=1', status_code=303)
    if totp_mod.is_enabled() and not totp_mod.verify(code):
        return RedirectResponse('/login?error=1', status_code=303)
    response = RedirectResponse('/', status_code=303)
    issue_session_cookie(response)
    return response


@app.post('/logout')
async def logout():
    response = RedirectResponse('/login', status_code=303)
    clear_session_cookie(response)
    return response


# --- Passkeys (WebAuthn) ------------------------------------------------------

PK_CHAL_COOKIE = 'pk_chal'

def _passkey_origin(request: Request) -> str:
    origin = request.headers.get('origin')
    if origin not in PASSKEY_ORIGINS:
        raise HTTPException(status_code=400, detail='unrecognized origin')
    return origin

def _set_challenge_cookie(resp, tok: str):
    resp.set_cookie(PK_CHAL_COOKIE, tok, max_age=passkey.CHALLENGE_TTL,
                    httponly=True, secure=True, samesite='strict', path='/passkey')


@app.get('/passkey/available')
async def passkey_available():
    return {'available': passkey.has_credentials()}


@app.get('/passkey/auth/options')
async def passkey_auth_options():
    if not passkey.has_credentials():
        raise HTTPException(status_code=404, detail='no passkeys registered')
    opts_json, tok = passkey.authentication_options()
    resp = JSONResponse(content=json.loads(opts_json))
    _set_challenge_cookie(resp, tok)
    return resp


@app.post('/passkey/auth/verify')
async def passkey_auth_verify(request: Request, credential: dict = Body(...)):
    origin = _passkey_origin(request)
    tok = request.cookies.get(PK_CHAL_COOKIE)
    try:
        passkey.verify_authentication(credential, tok, origin)
    except Exception as e:
        logging.warning('passkey auth failed: %s', e)
        raise HTTPException(status_code=401, detail='passkey verification failed')
    resp = JSONResponse(content={'ok': True})
    resp.delete_cookie(PK_CHAL_COOKIE, path='/passkey')
    issue_session_cookie(resp)
    return resp


@app.get('/passkey', response_class=HTMLResponse)
async def passkey_manage(request: Request, _: None = Depends(require_auth)):
    return templates.TemplateResponse(request, 'passkeys.html',
                                      {'credentials': passkey.list_credentials()})


@app.get('/passkey/register/options')
async def passkey_register_options(request: Request, _: None = Depends(require_auth)):
    opts_json, tok = passkey.registration_options()
    resp = JSONResponse(content=json.loads(opts_json))
    _set_challenge_cookie(resp, tok)
    return resp


@app.post('/passkey/register/verify')
async def passkey_register_verify(request: Request, payload: dict = Body(...),
                                  _: None = Depends(require_auth)):
    origin = _passkey_origin(request)
    tok = request.cookies.get(PK_CHAL_COOKIE)
    try:
        passkey.verify_registration(payload.get('credential', {}), tok, origin,
                                    payload.get('name', 'passkey'))
    except Exception as e:
        logging.warning('passkey registration failed: %s', e)
        raise HTTPException(status_code=400, detail='passkey registration failed')
    resp = JSONResponse(content={'ok': True})
    resp.delete_cookie(PK_CHAL_COOKIE, path='/passkey')
    return resp


@app.post('/passkey/credentials/delete')
async def passkey_delete(request: Request, payload: dict = Body(...),
                         _: None = Depends(require_auth)):
    ok = passkey.delete_credential(payload.get('id', ''))
    return {'ok': ok}


# --- TOTP (authenticator-app 2FA) ---------------------------------------------

@app.get('/totp', response_class=HTMLResponse)
async def totp_manage(request: Request, error: str | None = None,
                      _: None = Depends(require_auth)):
    if totp_mod.is_enabled():
        return templates.TemplateResponse(request, 'totp.html', {'enabled': True})
    secret = totp_mod.new_secret()  # pending until confirmed with a live code
    return templates.TemplateResponse(request, 'totp.html', {
        'enabled': False, 'secret': secret,
        'qr': totp_mod.qr_data_uri(secret), 'error': error,
    })


@app.post('/totp/enable')
async def totp_enable(request: Request, secret: str = Form(...), code: str = Form(...),
                      _: None = Depends(require_auth)):
    if not totp_mod.enable(secret, code):
        return RedirectResponse('/totp?error=1', status_code=303)
    return RedirectResponse('/totp', status_code=303)


@app.post('/totp/disable')
async def totp_disable(request: Request, _: None = Depends(require_auth)):
    totp_mod.disable()
    return RedirectResponse('/totp', status_code=303)


@app.get('/', response_class=HTMLResponse)
async def home(request: Request, _: None = Depends(require_auth)):
    return templates.TemplateResponse(request, 'dashboard.html')


def _tools_token(request: Request) -> str:
    """Read a feed token from `Authorization: Bearer <t>` or `?token=<t>`."""
    auth = request.headers.get('authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:].strip()
    return request.query_params.get('token', '')


@app.get('/stack', response_class=HTMLResponse)
@app.get('/tools', response_class=HTMLResponse)
async def tools_private(request: Request, _: None = Depends(require_auth)):
    # The full private tools page (private repo names + the 'Where to focus next' gap
    # analysis). HUMAN/session only — the gap analysis is a private self-guide and is
    # never exposed to the token feed. Generated into data/tools-private.html.
    p = BASE_DIR / 'data' / 'tools-private.html'
    if not p.exists():
        return HTMLResponse('<p>Private tools view not generated yet.</p>', status_code=503)
    return HTMLResponse(p.read_text())


@app.get('/stack-agent-view', response_class=HTMLResponse)
async def stack_agent_view(request: Request, _: None = Depends(require_auth)):
    # Session-gated preview of exactly what stephens.page/stack.json returns to an
    # agent: the private feed (with token) and the public feed (without). Lets the human
    # see what the bearer token exposes before sharing it.
    def load(name):
        p = BASE_DIR / 'data' / name
        return json.dumps(json.loads(p.read_text()), indent=2) if p.exists() else '(not generated yet)'
    return templates.TemplateResponse(request, 'agent-view.html', {
        'feed_json': load('tools-feed.json'),
        'public_json': load('tools-public.json'),
    })


@app.get('/stack.json')
@app.get('/tools.json')
async def tools_feed(request: Request):
    # Machine-readable feed for a remote AI agent. With a valid bearer token (or a
    # logged-in session): the PRIVATE feed — private repo NAMES + tech distribution,
    # but no 'Where to focus next' gaps. With NO token: the PUBLIC feed — aggregate
    # only, no private names (same data as tools.stephens.page). A WRONG token is 401.
    tok = _tools_token(request)
    if tok:
        if not (TOOLS_FEED_TOKEN and secrets.compare_digest(tok, TOOLS_FEED_TOKEN)):
            raise HTTPException(status_code=401, detail='invalid tools feed token')
        name = 'tools-feed.json'        # authorized: private names, no gaps
    elif is_authenticated(request):
        name = 'tools-feed.json'        # logged-in human: private names, no gaps
    else:
        name = 'tools-public.json'      # no token: public aggregate, no names
    p = BASE_DIR / 'data' / name
    if not p.exists():
        raise HTTPException(status_code=503, detail='tools feed not generated yet')
    return JSONResponse(content=json.loads(p.read_text()))


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
    # If require_auth threw a 303, honor it as a redirect; otherwise fall back to
    # FastAPI's default handler (re-raising here would turn every 4xx into a 500).
    if exc.status_code == 303 and 'Location' in (exc.headers or {}):
        return RedirectResponse(exc.headers['Location'], status_code=303)
    return await default_http_exception_handler(request, exc)
