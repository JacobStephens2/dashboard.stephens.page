"""TOTP (authenticator-app) two-factor for the dashboard password login.

Once enabled, the password login also requires a 6-digit code from an authenticator
app (Ente Auth, Aegis, Google Authenticator, ...). Setup is a standard otpauth:// QR
scanned into the app. Passkeys are a separate strong path and are NOT gated by TOTP.

Single admin: the secret lives in one JSON file (mode 600). Enabling requires
confirming a live code first, so a mis-scanned secret can't lock the password out.
"""
import json
import os
from pathlib import Path

import base64
from io import BytesIO

import pyotp
import qrcode

from .config import TOTP_FILE

TOTP_PATH = Path(TOTP_FILE)
ISSUER = "stephens.page dashboard"
ACCOUNT = "jacob"


def _load() -> dict:
    if TOTP_PATH.exists():
        return json.loads(TOTP_PATH.read_text())
    return {}


def _save(d: dict) -> None:
    TOTP_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOTP_PATH.write_text(json.dumps(d))
    os.chmod(TOTP_PATH, 0o600)


def is_enabled() -> bool:
    return bool(_load().get("enabled"))


def verify(code: str) -> bool:
    d = _load()
    secret = d.get("secret")
    if not (d.get("enabled") and secret and code):
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=ACCOUNT, issuer_name=ISSUER)


def qr_data_uri(secret: str) -> str:
    """High-contrast black-on-white PNG QR as a data URI (renders well on any theme)."""
    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(provisioning_uri(secret))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def enable(secret: str, code: str) -> bool:
    """Confirm a live code against the pending secret, then persist it as enabled."""
    if not secret or not pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1):
        return False
    _save({"secret": secret, "enabled": True})
    return True


def disable() -> None:
    _save({})
