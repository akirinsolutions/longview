"""Accounts and sessions — the login feature.

Per-person storage needs a per-person identity, so this module holds
the whole identity story:

- accounts: a small JSON store under ``data/accounts.json`` (an env var
  ``LONGVIEW_ACCOUNTS`` moves it; tests point it at a scratch file).
  Every username is stored lowercase; every password is stored as a
  PBKDF2-HMAC-SHA256 hash with a random salt and never in clear.
- sessions: one httponly cookie, ``longview_session``, carrying
  ``username.expiry.signature``. The signature keys on a per-machine
  secret (``data/secret.key``, generated once, written 0600), so the
  cookie is valid across restarts and before any deploy.
- the current-user context: set by the auth middleware from the cookie
  at the start of a request, and by session owners who pass a user
  explicitly into background threads. Vault resolution reads it, so
  every route — and every thread — writes to the right person's file.

The store is never synced anywhere and never logged: a login failure
says only "Wrong username or password" and nothing about why. Failed
logins are throttled per username (in memory, per process) to slow
down guessing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from contextvars import ContextVar
from pathlib import Path

# Test seam (the autouse conftest fixture points the whole data dir at
# a scratch directory); the default honors the same env var the vault
# uses, so self-hosters who move their data move accounts with it.
DATA_DIR = Path(
    os.environ.get("LONGVIEW_DATA_DIR")
    or os.environ.get("PROOF_DATA_DIR")
    or (Path(__file__).resolve().parent.parent / "data"))
ACCOUNTS_PATH = Path(os.environ.get("LONGVIEW_ACCOUNTS")
                     or DATA_DIR / "accounts.json")
SECRET_PATH = Path(os.environ.get("LONGVIEW_SECRET")
                   or DATA_DIR / "secret.key")

COOKIE_NAME = "longview_session"
COOKIE_GOOGLE_STATE = "longview_google"
SESSION_SECONDS = 30 * 24 * 3600        # one month — a week is long enough to be honest
SIGN_IN_MAX_FAILS = 5                  # per username, within this window
SIGN_IN_WINDOW = 600                   # seconds

_USER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
_PBKDF2_ROUNDS = 200_000

_LOCK = threading.RLock()
_ACTIVE: ContextVar[str | None] = ContextVar("longview_active_user",
                                            default=None)
# In-memory failed-login attempts, per username. Per process by design:
# a restarted instance simply forgets, and a free host restarts often.
_FAILURES: dict[str, list[float]] = {}


class AccountError(ValueError):
    """A plain-English problem with a sign-up or sign-in attempt."""


class ThrottleError(AccountError):
    """Too many failed tries — the route answers 429, not 401."""


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

def _read_store() -> dict:
    try:
        d = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": 1, "users": {}}
    if not isinstance(d, dict) or d.get("v") != 1:
        return {"v": 1, "users": {}}
    return d


def _write_store(store: dict) -> None:
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS_PATH.with_name(ACCOUNTS_PATH.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=1), encoding="utf-8")
    tmp.replace(ACCOUNTS_PATH)


def _secret() -> bytes:
    """The per-machine signing secret. Generated once, never sent anywhere."""
    with _LOCK:
        try:
            hex_key = SECRET_PATH.read_text(encoding="utf-8").strip()
            key = bytes.fromhex(hex_key)
            if len(key) >= 16:
                return key
        except (OSError, ValueError):
            pass
        key = secrets.token_bytes(32)
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SECRET_PATH.with_name(SECRET_PATH.name + ".tmp")
        tmp.write_text(key.hex(), encoding="utf-8")
        tmp.replace(SECRET_PATH)
        try:
            os.chmod(SECRET_PATH, 0o600)
        except OSError:
            pass
        return key


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS).hex()


# ---------------------------------------------------------------------------
# signing in
# ---------------------------------------------------------------------------

def _username_clean(value) -> str:
    u = str(value or "").strip().lower()
    if not _USER_RE.match(u):
        raise AccountError(
            "Pick a username with 3–32 characters: lowercase letters, "
            "numbers, hyphens or underscores.")
    return u


def signup(username: str, password: str) -> str:
    """Create a free account. Returns the username (lowercased).

    Raises AccountError in plain English on a bad username, a short
    password, or a name taken — the route turns that into a 400."""
    u = _username_clean(username)
    pw = str(password or "")
    if len(pw) < 8:
        raise AccountError("Pick a password of at least 8 characters.")
    if len(pw) > 256:
        raise AccountError("Passwords can't be longer than 256 characters — "
                           "and 8 is plenty.")
    with _LOCK:
        store = _read_store()
        if u in store["users"]:
            raise AccountError("That username is taken — try another one.")
        salt = secrets.token_bytes(16)
        store["users"][u] = {
            "salt": salt.hex(),
            "hash": _hash_password(pw, salt),
            "created": int(time.time()),
        }
        _write_store(store)
    return u


def login(username: str, password: str) -> str:
    """Verify a pair. Returns the username (lowercased) or raises
    AccountError in plain English. Every failure message is identical —
    never hint at whether the name or the password was the wrong part."""
    u = str(username or "").strip().lower()
    pw = str(password or "")
    now = time.time()
    fails = _FAILURES.get(u, [])
    fails = [t for t in fails if now - t < SIGN_IN_WINDOW]
    if len(fails) >= SIGN_IN_MAX_FAILS:
        _FAILURES[u] = fails
        raise ThrottleError(
            "Too many tries — give it a few minutes, then come back.")
    store = _read_store()
    record = store.get("users", {}).get(u)
    ok = (record is not None
          and hmac.compare_digest(record.get("hash", ""),
                                  _hash_password(pw, bytes.fromhex(record["salt"]))))
    if not ok:
        fails.append(now)
        _FAILURES[u] = fails
        raise AccountError("Wrong username or password.")
    _FAILURES.pop(u, None)
    return u


def authenticate(username: str, password: str) -> tuple[str, str]:
    """Sign in for real: verify, then issue the cookie value. Returns
    ``(username, token)``."""
    u = login(username, password)
    return u, issue(u)


def issue(username: str) -> str:
    """A session token for the user: ``username.expiry.signature``.

    The token is self-contained (no server-side session store), so a
    restart or a free-tier wake-up costs nothing extra. The signature
    keys on a per-machine secret that never leaves the host."""
    expiry = int(time.time()) + SESSION_SECONDS
    msg = f"{username}:{expiry}".encode("utf-8")
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()
    return f"{username}.{expiry}.{sig}"


def read_token(token: str | None) -> str | None:
    """The user behind a cookie value, or None if it is not ours or is
    expired. Never raises."""
    if not token or "." not in token:
        return None
    try:
        username, expiry_s, sig = token.rsplit(".", 2)
        expiry = int(expiry_s)
    except (ValueError, AttributeError):
        return None
    if time.time() > expiry:
        return None
    if not _USER_RE.match(username):
        return None
    msg = f"{username}:{expiry_s}".encode("utf-8")
    expected = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    # The account must still exist — a deleted account's cookie dies.
    store = _read_store()
    if username not in store.get("users", {}):
        return None
    return username


# ---------------------------------------------------------------------------
# the current user
# ---------------------------------------------------------------------------

def current_user() -> str | None:
    """The username of the request in progress (or of the current
    background thread), else None for anonymous use."""
    return _ACTIVE.get()


def set_user(username: str | None):
    """Bind the current scope to a user (the middleware does this per
    request; background threads do it explicitly). Returns a reset
    token to pass to the matching ``reset``."""
    return _ACTIVE.set(username)


def reset_user(token) -> None:
    _ACTIVE.reset(token)


def has_accounts() -> bool:
    """Whether the instance has ever been signed up to — the gate the
    front end reads to know whether to show the sign-in card."""
    return bool(_read_store().get("users"))


# ---------------------------------------------------------------------------
# Google sign-in (OAuth 2.0 + OpenID Connect)
#
# A second way in, alongside the password form. The user clicks "Sign in
# with Google", this module redirects to Google's authorization page,
# Google redirects back with a code, and the exchange happens server-side
# with the Client Secret held in the environment — never in the bundle.
#
# No JWT library: the id_token signature is verified by Google's own
# tokeninfo endpoint (the documented "simple" path), which costs one
# round trip to Google and no new dependencies. The stable identity is
# Google's ``sub`` (an opaque, never-reused user id), never the email —
# email addresses change, subs do not. A Google account is provisioning
# for a fresh sign-in: no password, no salt beyond what the file needs
# to look like a record.
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID_ENV = "LONGVIEW_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_ENV = "LONGVIEW_GOOGLE_CLIENT_SECRET"
GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


def google_configured() -> bool:
    """True when the instance carries the Google OAuth client pair."""
    return bool(os.environ.get(GOOGLE_CLIENT_ID_ENV)
                and os.environ.get(GOOGLE_CLIENT_SECRET_ENV))


def google_auth_url(state: str, redirect_uri: str) -> str:
    """The Google authorization URL the browser should go to."""
    from urllib.parse import urlencode
    params = {
        "client_id": os.environ[GOOGLE_CLIENT_ID_ENV],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE}?{urlencode(params)}"


def google_exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange the authorization code for a token pair (server-side)."""
    import httpx
    r = httpx.post(
        GOOGLE_TOKEN,
        data={
            "code": code,
            "client_id": os.environ[GOOGLE_CLIENT_ID_ENV],
            "client_secret": os.environ[GOOGLE_CLIENT_SECRET_ENV],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def google_verify_id_token(id_token: str, client_id: str) -> dict:
    """Verify an id_token via Google's own tokeninfo endpoint.

    Raises on anything that does not check out. Returns the claims
    dict on success — never passes through anything unsigned."""
    if not id_token:
        raise ValueError("Google returned no id_token")
    import httpx
    r = httpx.get(GOOGLE_TOKENINFO,
                  params={"id_token": id_token}, timeout=30)
    r.raise_for_status()
    claims = r.json()
    if not isinstance(claims, dict):
        raise ValueError("Google's answer didn't check out")
    if claims.get("aud") != client_id:
        raise ValueError("that token wasn't issued for this application")
    iss = claims.get("iss") or ""
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("that token came from the wrong issuer")
    try:
        exp = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        raise ValueError("that token has no usable expiry")
    if exp <= time.time():
        raise ValueError("that token has expired — sign in again")
    if not claims.get("sub"):
        raise ValueError("that token carries no stable identity")
    return claims


def _google_username(email: str, existing: set) -> str:
    """A stable, valid username for a Google identity: the local part
    of the email, lowercased and sanitized, de-duplicated."""
    local = (email or "").split("@")[0].lower()
    base = re.sub(r"[^a-z0-9_-]+", "-", local).strip("-_")[:28]
    if not base:
        base = "google"
    if len(base) < 3:
        base = (base + "-" + secrets.token_hex(2))[:3]
    if not _USER_RE.match(base):
        base = "google" + secrets.token_hex(3)
    u, i = base, 2
    while u in existing:
        u = f"{base}-{i}"
        i += 1
    return u


def google_provision_user(sub: str, email: str = "") -> str:
    """Find the account for a Google sign-in, creating it if needed.

    Matches by Google's stable ``sub`` first — a changed email does not
    mint a new account. Returns the username (lowercased)."""
    with _LOCK:
        store = _read_store()
        for u, rec in store.get("users", {}).items():
            if rec.get("sub") == sub:
                return u
        u = _google_username(email, set(store.get("users", {})))
        salt = secrets.token_bytes(16)
        store["users"][u] = {
            "salt": salt.hex(),
            "hash": "",                    # google accounts have no password
            "method": "google",
            "sub": sub,
            "created": int(time.time()),
        }
        _write_store(store)
        return u
