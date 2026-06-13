"""WebAuthn passkey registration + authentication for the dashboard.

Passkeys are added ALONGSIDE the existing password login (password stays as a
fallback so a lost authenticator can't lock the admin out). Registration requires
an already-authenticated session; authentication issues the same `dash_session`
cookie the password flow uses, so every require_auth route - including the gated
tools view - is passkey-protected for free.

Single admin: credentials live in one JSON file (mode 600). Challenges are held
in memory keyed by a short-lived token cookie (single uvicorn worker, so a plain
dict is fine).
"""
import json
import os
import secrets
import time
from pathlib import Path

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)

from .config import PASSKEY_RP_ID, PASSKEY_RP_NAME, PASSKEY_FILE

CRED_FILE = Path(PASSKEY_FILE)
ADMIN_USER_ID = b"jacob-admin"          # stable user handle (one admin)
CHALLENGE_TTL = 300                     # seconds

_challenges: dict[str, tuple[bytes, float]] = {}


# --- credential storage -------------------------------------------------------

def _load() -> list[dict]:
    if CRED_FILE.exists():
        return json.loads(CRED_FILE.read_text())
    return []


def _save(creds: list[dict]) -> None:
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CRED_FILE.write_text(json.dumps(creds, indent=1))
    os.chmod(CRED_FILE, 0o600)


def list_credentials() -> list[dict]:
    """Public, secret-free view for the manage UI."""
    return [{"id": c["id"], "name": c.get("name", "passkey"), "added": c.get("added")}
            for c in _load()]


def has_credentials() -> bool:
    return bool(_load())


def delete_credential(cred_id: str) -> bool:
    creds = _load()
    kept = [c for c in creds if c["id"] != cred_id]
    if len(kept) == len(creds):
        return False
    _save(kept)
    return True


# --- challenge handling -------------------------------------------------------

def _put_challenge(challenge: bytes) -> str:
    now = time.time()
    for k in [k for k, (_, exp) in _challenges.items() if exp < now]:
        _challenges.pop(k, None)
    tok = secrets.token_urlsafe(18)
    _challenges[tok] = (challenge, now + CHALLENGE_TTL)
    return tok


def _take_challenge(tok: str | None) -> bytes | None:
    if not tok:
        return None
    item = _challenges.pop(tok, None)
    if not item:
        return None
    challenge, exp = item
    return challenge if exp >= time.time() else None


# --- registration -------------------------------------------------------------

def registration_options() -> tuple[str, str]:
    existing = _load()
    opts = generate_registration_options(
        rp_id=PASSKEY_RP_ID,
        rp_name=PASSKEY_RP_NAME,
        user_id=ADMIN_USER_ID,
        user_name="jacob",
        user_display_name="Jacob Stephens",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"])) for c in existing
        ],
    )
    return options_to_json(opts), _put_challenge(opts.challenge)


def verify_registration(credential: dict, tok: str, origin: str, name: str) -> None:
    challenge = _take_challenge(tok)
    if challenge is None:
        raise ValueError("registration challenge expired or missing")
    ver = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=PASSKEY_RP_ID,
        expected_origin=origin,
    )
    creds = _load()
    creds.append({
        "id": bytes_to_base64url(ver.credential_id),
        "public_key": bytes_to_base64url(ver.credential_public_key),
        "sign_count": ver.sign_count,
        "name": (name or "passkey").strip()[:40],
        "added": time.strftime("%Y-%m-%d"),
    })
    _save(creds)


# --- authentication -----------------------------------------------------------

def authentication_options() -> tuple[str, str]:
    creds = _load()
    opts = generate_authentication_options(
        rp_id=PASSKEY_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"])) for c in creds
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json(opts), _put_challenge(opts.challenge)


def verify_authentication(credential: dict, tok: str, origin: str) -> bool:
    challenge = _take_challenge(tok)
    if challenge is None:
        raise ValueError("authentication challenge expired or missing")
    creds = _load()
    rec = next((c for c in creds if c["id"] == credential.get("id")), None)
    if rec is None:
        raise ValueError("unknown credential")
    ver = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=PASSKEY_RP_ID,
        expected_origin=origin,
        credential_public_key=base64url_to_bytes(rec["public_key"]),
        credential_current_sign_count=rec["sign_count"],
    )
    rec["sign_count"] = ver.new_sign_count
    _save(creds)
    return True
