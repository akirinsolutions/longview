"""Cloud backup — a second, permanent copy of each person's file.

The per-person vault lives on the host's disk: on a free tier that disk
can be wiped by a redeploy or a reset. The save file is the permanent
copy; the cloud copy is the other one. Each file is a few kilobytes,
so a durable home is cheap: a private GitHub repository, one file per
signed-in person, a commit per backup.

Configuration is opt-in, set by the site operator in the environment:

    LONGVIEW_BACKUP_REPO=owner/repo    the private repository
    LONGVIEW_BACKUP_TOKEN=...          a GitHub token with
                                       contents:write for that repo

The token never enters the bundle, the repo, or the response — the app
sends it only to api.github.com. The backup is always best-effort: a
failure never fails the save, and a per-user cooldown stops a noisy
session from hammering the API. A failed backup is reported in plain
words; it is never silently swallowed.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time

REPO_ENV = "LONGVIEW_BACKUP_REPO"
TOKEN_ENV = "LONGVIEW_BACKUP_TOKEN"

_COOLDOWN = 60          # seconds between automatic backups per user
_last_backup: dict[str, float] = {}
_lock = threading.Lock()


def configured() -> bool:
    """True when the instance carries both the repo and a token."""
    return bool(os.environ.get(REPO_ENV)
                and os.environ.get(TOKEN_ENV))


def _repo() -> tuple[str, str] | None:
    """(owner, repo) from the env var, or None when it is malformed."""
    parts = (os.environ.get(REPO_ENV) or "").split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def backup_vault(username: str, vault_dict: dict, *,
                 force: bool = False) -> dict:
    """Push the vault to the cloud copy. Never raises.

    Returns ``{"ok": bool, "detail": str}``. Automatic backups (``force``
    False) honour a per-user cooldown; an explicit backup never does.
    """
    import httpx  # kept importable for tests
    token = os.environ.get(TOKEN_ENV)
    if not token:
        return {"ok": False, "detail": "backup is not configured on this instance"}
    repo = _repo()
    if repo is None:
        return {"ok": False, "detail": "backup repo is not set up correctly"}
    owner, name = repo
    with _lock:
        last = _last_backup.get(username, 0.0)
        if not force and time.time() - last < _COOLDOWN:
            return {"ok": True, "detail": "already backed up within the last minute"}
        _last_backup[username] = time.time()

    path = f"users/{username}.json"
    content = base64.b64encode(
        json.dumps(vault_dict, indent=1).encode("utf-8")).decode("ascii")
    try:
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
        # The file exists on later backups: read its current SHA first.
        r = httpx.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            sha = r.json().get("sha")
            body = {"message": f"Backup for {username}",
                    "content": content, "sha": sha}
        elif r.status_code == 404:
            body = {"message": f"Backup for {username}", "content": content}
        else:
            return {"ok": False, "detail": f"GitHub answered {r.status_code}"}
        r = httpx.put(url, headers=headers, json=body, timeout=20)
        if r.status_code in (200, 201):
            return {"ok": True, "detail": "backed up to the cloud copy"}
        return {"ok": False, "detail": f"GitHub answered {r.status_code}"}
    except Exception:
        return {"ok": False, "detail": "could not reach GitHub just now"}
