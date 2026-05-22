import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from .config import ADMIN_PASSWORD_HASH, SESSION_SECRET

SESSION_COOKIE = 'dash_session'
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_signer = URLSafeTimedSerializer(SESSION_SECRET, salt='dashboard-session')


def verify_password(password: str) -> bool:
    return bcrypt.checkpw(password.encode(), ADMIN_PASSWORD_HASH.encode())


def issue_session_cookie(response):
    token = _signer.dumps({'admin': True})
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_MAX_AGE,
        httponly=True, secure=True, samesite='strict',
        path='/',
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path='/')


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        _signer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_auth(request: Request):
    if not is_authenticated(request):
        # HTMX requests get a 401 so they can redirect client-side;
        # full page requests get a redirect to /login.
        if request.headers.get('hx-request') == 'true':
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={'Location': '/login'},
        )
