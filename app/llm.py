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

Only the standard library plus the existing ``httpx`` dependency.
"""

from __future__ import annotations

import base64
import binascii
import contextvars
import json
import os
from typing import Any, Optional

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
