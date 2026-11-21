"""Longview's language-model configuration — one seam, every caller.

Resolution order, first that supplies a key wins per-field:

1. An explicit config dict from the caller. Background jobs (study
   search, the strategy lab) run in fresh threads that cannot see the
   request, so their routes capture ``resolve()`` at request time and
   pass the dict in.
2. The per-request override sent by the browser as an
   ``X-Longview-LLM`` header (base64 of ``{"base", "key", "model"}``),
   held in a context variable the app middleware sets.
3. Environment variables: ``LONGVIEW_LLM_KEY`` / ``LONGVIEW_LLM_BASE`` /
   ``LONGVIEW_LLM_MODEL``, with the legacy ``PROOF_LLM_*`` names kept
   as fallbacks so existing setups keep working.

The app never stores a key. A request-scoped key rides the request, is
passed through to the model provider, and is forgotten; a
server-deployed key lives in the environment. Either way, one model
answers everything on the request.

The base URL is vetted before any call (``validate_base``): a hosted
instance must not be a proxy into someone else's intranet or at a
cloud metadata address, so the app only calls https addresses that
resolve to public hosts, plus the loopback over plain http for a model
running on the reader's own machine.

Only the standard library plus the existing ``httpx`` dependency.
"""

from __future__ import annotations

import base64
import binascii
import contextvars
import ipaddress
import json
import os
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

# The request-scoped override, set by middleware from the header.
_request_override: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "longview_llm_override", default=None)

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# (Longview name, legacy Proof name) pairs.
_ENV_VARS = (
    ("key", "LONGVIEW_LLM_KEY", "PROOF_LLM_KEY"),
    ("base", "LONGVIEW_LLM_BASE", "PROOF_LLM_BASE"),
    ("model", "LONGVIEW_LLM_MODEL", "PROOF_LLM_MODEL"),
)


def parse_header(raw: str | None) -> Optional[dict]:
    """Decode an ``X-Longview-LLM`` header.

    The value is base64 of a JSON object with any of
    ``base`` / ``key`` / ``model`` (plain strings). Anything that is not
    a decodable object of strings is rejected silently — a bad header
    must never take the request down, it just falls through to the
    server's own configuration.
    """
    if not raw:
        return None
    try:
        obj = json.loads(base64.b64decode(raw, validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    out = {}
    for field in ("base", "key", "model"):
        value = obj.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()
    return out or None


def validate_base(base: str) -> Optional[str]:
    """Check a model base URL before any call is made with it.

    Returns a plain-English problem, or None when the address may be
    called. The rules:

    - https may be used for any host, but only when its name resolves
      to public addresses. Private (10/8, 172.16/12, 192.168/16),
      link-local (169.254/16 — the cloud metadata address), and other
      non-public targets are refused: a public instance must not fetch
      from a reader's intranet.
    - plain http may be used only for the loopback (127.0.0.1,
      ::1, localhost) — the shape of a self-host pointed at a model
      running on the reader's own machine.
    - any other scheme is refused outright.

    The name is resolved and *every* answer is checked; a name that
    answers with even one non-public address is refused. (A name whose
    DNS answer changes between the check and the connect — a rebinding
    trick — is the residual risk this design accepts; the hosts it
    could reach are the app's own container, nothing shared.)
    """
    try:
        u = urlparse((base or "").strip())
    except Exception:
        return "That model address doesn't look like an address — it " \
               "should look like https://provider.example.com/v1."
    if u.scheme not in ("http", "https"):
        return f"Model addresses use https (or http for a model on your " \
               f"own machine) — “{u.scheme or 'no scheme'}://” is neither."
    host = u.hostname
    if not host:
        return "That model address has no host in it — it should look " \
               "like https://provider.example.com/v1."
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return "I couldn't look up the name in that model address — is " \
               "it spelled right?"
    except Exception:
        return "That model address didn't look up cleanly — check it in " \
               "Settings."
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_loopback:
            continue
        if ip.is_global and not ip.is_private and not ip.is_reserved \
                and not ip.is_unspecified:
            continue
        if u.scheme == "http":
            return "Plain http is only for a model running on your own " \
                   "machine (127.0.0.1). For a hosted model, use its " \
                   "https address."
        return "That model address points at a private or internal " \
               "network. I only call public https addresses (or your " \
               "own machine over http)."
    return None


def resolve(config: Optional[dict] = None) -> dict:
    """The effective model configuration for the current call.

    Explicit ``config`` wins per-field, then the request override
    (context variable), then the environment (with the legacy
    ``PROOF_LLM_*`` fallbacks). Always returns all three fields, with
    the documented defaults where nothing was set; ``key`` is ``""``
    when no key is configured at any layer.
    """
    ovr = _request_override.get()
    env = {
        field: next((os.environ.get(n) or "" for n in names if os.environ.get(n)), "")
        for field, *names in _ENV_VARS
    }
    out = {"base": DEFAULT_BASE, "key": "", "model": DEFAULT_MODEL}
    for layer in (env, ovr, config):
        if not layer:
            continue
        for field in ("base", "key", "model"):
            value = (layer.get(field) or "").strip()
            if value:
                out[field] = value
    out["base"] = out["base"].rstrip("/")
    return out


def is_configured(config: Optional[dict] = None) -> bool:
    """True when the effective configuration has a key."""
    return bool(resolve(config)["key"])


def set_request_override(config: Optional[dict]) -> None:
    """Middleware entry point: hold a request's header config in the
    context variable the seam reads."""
    _request_override.set(config)


def request_override() -> Optional[dict]:
    """The current request's header config, if any (for status views)."""
    return _request_override.get()


def post_chat(system: str, user: str, config: Optional[dict] = None,
              *, max_tokens: int = 4000, timeout: float = 60.0,
              temperature: float = 0.0) -> tuple[str, str]:
    """One chat completion against the resolved configuration.

    Returns ``(content, model)`` — the content of the reply, or ``""``
    when the model returned nothing. Raises ``RuntimeError`` in plain
    English on any failure; the routes turn those into friendly errors.
    Raises ``RuntimeError("no key")`` when no key is configured at any
    layer, so callers can keep their 503 behavior.
    """
    cfg = resolve(config)
    if not cfg["key"]:
        raise RuntimeError("no key")
    problem = validate_base(cfg["base"])
    if problem:
        raise RuntimeError(problem)
    payload = {
        "model": cfg["model"], "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        r = httpx.post(
            cfg["base"] + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg['key']}"},
            json=payload, timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"the model didn't answer within {int(timeout)} seconds — it "
            f"may be busy or slow just now; try again") from None
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"the model's endpoint didn't answer ({type(e).__name__}) — "
            f"is the model server running? try again") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError(
            "the model's answer didn't come back in the shape we read — "
            "try again") from None
    return (data["choices"][0]["message"]["content"] or "").strip(), cfg["model"]
