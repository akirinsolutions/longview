"""One file for everything the reader owns.

In a signed-in session the file is per person: ``data/users/<username>/longview.json``
(no external service, no database — the free host's disk is the cloud).
In an anonymous session it stays the one shared file, as before.

All of the app's user data — the portfolio, the note pages, the risk
moves, the fund roster, the research reports, the economy-tree
overrides — lives in a single JSON file:

    data/longview.json        (``LONGVIEW_VAULT`` moves it;
                               ``PROOF_VAULT`` is read as a fallback)

    {
      "v": 1,
      "updated": 1732012345,
      "sections": {
        "portfolio": {…} | null,
        "notes":     {…} | null,
        "risk":      {…} | null,
        "roster":    {…} | null,
        "research":  {…} | null,
        "economy":   {…} | null
      }
    }

Each section is exactly the envelope that module's old data file
carried — ``data/portfolio.json`` and friends — so the bytes are
compatible: a section reads as if the old file were there, and a write
replaces that section of the one file. The legacy files stay on disk
(untracked); the first time the vault is read on a machine that has
them, they are folded into it and that is the end of the
per-module files.

Why one file: the reader's data should fit in one download. Export is
a file, import is a file, and moving between a self-hosted instance
and the public one is "save the file here, upload it there." The
server itself stores the same one file; on a host with an ephemeral
disk the file may be wiped, and the reader re-imports it — nothing is
lost that the file didn't hold.

The client keeps a mirror of this file in localStorage and syncs on
load (the newer ``updated`` wins); the export/import buttons work
against the mirror, and ``GET/PUT /api/vault`` serve the rest.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

#: The directory the legacy per-module files were folded in from. A
#: module attribute (not a constant) so tests can point it at a scratch
#: directory and a corrupt vault reads as *empty*, not as whatever the
#: developer's real data/ folder holds.
LEGACY_DIR = Path(__file__).resolve().parent.parent / "data"

VAULT_PATH = Path(os.environ.get(
    "LONGVIEW_VAULT",
    os.environ.get("PROOF_VAULT", str(LEGACY_DIR / "longview.json")),
))

#: Where per-user vault files live (anonymous mode never writes here).
USERS_DIR = Path(os.environ.get("LONGVIEW_USERS_DIR")
                 or str(LEGACY_DIR / "users"))


def current_path() -> Path:
    """The vault file in effect for this scope: the signed-in user's
    file when one is set (request context or an explicitly-passed
    thread), otherwise the shared file. A fresh per-user file is empty
    and is only written on first save."""
    from . import accounts  # lazy: the vault must not import the store
    user = accounts.current_user()
    if not user:
        return VAULT_PATH
    return USERS_DIR / user / "longview.json"


VERSION = 1

#: Section name → the legacy file it was folded in from, in the order
#: the UI lists them. "research" is the old study.json: its saved
#: notes are reports now, so the key moves from "notes" to "reports".
SECTIONS = ("portfolio", "notes", "risk", "roster", "research", "economy")
_LEGACY_FILE = {
    "portfolio": "portfolio.json",
    "notes": "notes.json",
    "risk": "risk.json",
    "roster": "roster.json",
    "research": "study.json",
    "economy": "economy_tree.json",
}

_LOCK = threading.RLock()


def _skeleton() -> dict:
    return {
        "v": VERSION,
        "updated": 0,
        "sections": {name: None for name in SECTIONS},
    }


def _read_file() -> dict | None:
    """The vault file as a normalised dict, or None if missing/corrupt."""
    try:
        d = json.loads(current_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict) or d.get("v") != VERSION:
        return None
    out = _skeleton()
    try:
        out["updated"] = int(d.get("updated") or 0)
    except (TypeError, ValueError):
        out["updated"] = 0
    secs = d.get("sections")
    if isinstance(secs, dict):
        for name in SECTIONS:
            s = secs.get(name)
            if isinstance(s, dict):
                out["sections"][name] = s
    return out


def _legacy_section(name: str) -> dict | None:
    """One legacy file as a section envelope, or None if absent."""
    p = LEGACY_DIR / _LEGACY_FILE[name]
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict):
        return None
    if name == "research" and "reports" not in d and isinstance(d.get("notes"), list):
        # The old study section's saved notes are research reports.
        d = dict(d)
        d["reports"] = d.pop("notes")
    return d


def _write_locked(v: dict) -> None:
    """Atomic write; the caller holds the lock."""
    path = current_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(v, indent=1), encoding="utf-8")
    tmp.replace(path)


def _load_locked() -> dict:
    """The vault, folding the legacy files in once. Lock held."""
    v = _read_file()
    if v is not None:
        return v
    # The file is missing (or unreadable). Only anonymous use seeds
    # from the legacy files still on disk — a signed-in person's file
    # is their own and is never seeded from anyone else's.
    from . import accounts
    anonymous = not accounts.current_user()
    if not anonymous:
        return _skeleton()
    found = False
    v = _skeleton()
    for name in SECTIONS:
        s = _legacy_section(name)
        if s is not None:
            v["sections"][name] = s
            found = True
    if not found:
        return v
    v["updated"] = int(time.time())
    _write_locked(v)
    return v


def load() -> dict:
    """The whole vault. Never raises; corrupt reads as missing."""
    with _LOCK:
        return _load_locked()


def read_section(name: str) -> dict | None:
    """One section's envelope (the old file's shape), or None."""
    if name not in SECTIONS:
        raise KeyError(name)
    with _LOCK:
        return _load_locked()["sections"][name]


def write_section(name: str, envelope: dict | None) -> None:
    """Replace one section (a full envelope dict, or None to drop it)."""
    if name not in SECTIONS:
        raise KeyError(name)
    with _LOCK:
        v = _load_locked()
        v["sections"][name] = envelope
        v["updated"] = int(time.time())
        _write_locked(v)


def replace(sections: dict, updated: int | None = None) -> dict:
    """The import path: take the reader's file (or a file's sections),
    keep the known names, drop the rest, write the vault. Returns the
    new ``meta()``. Raises ValueError in plain English on a file that
    is not a vault in any acceptable shape."""
    if not isinstance(sections, dict):
        raise ValueError("that file is not a Longview data file — export one "
                         "from a browser where you have used the app")
    # Three acceptable shapes: a full vault, a vault's sections block,
    # or a bare {section: envelope} map.
    if "sections" in sections and isinstance(sections.get("sections"), dict):
        src = sections["sections"]
    elif any(k in sections for k in SECTIONS):
        src = sections
    elif sections and all(k in SECTIONS for k in sections):
        src = sections
    else:
        raise ValueError("that file doesn't look like a Longview data file — "
                         f"it should hold sections like {', '.join(SECTIONS)}")
    if updated is None and "sections" in sections:
        updated = sections.get("updated")
    with _LOCK:
        v = _skeleton()
        for name in SECTIONS:
            s = src.get(name)
            if isinstance(s, dict):
                v["sections"][name] = s
        try:
            v["updated"] = int(updated) if updated is not None else 0
        except (TypeError, ValueError):
            v["updated"] = 0
        if v["updated"] == 0:
            v["updated"] = int(time.time())
        _write_locked(v)
        return meta()


def meta() -> dict:
    """What the file holds, in the shape the UI shows: presence plus a
    per-section count where the envelope makes one obvious."""
    with _LOCK:
        v = _load_locked()
    out = {"updated": v["updated"], "sections": {}}
    for name, s in v["sections"].items():
        if s is None:
            out["sections"][name] = False
            continue
        count = None
        for key in ("positions", "pages", "moves", "funds", "reports", "tree"):
            val = s.get(key)
            if isinstance(val, list):
                count = len(val)
                break
            if isinstance(val, dict) and key == "moves":
                count = len(val)
                break
        out["sections"][name] = True
        if count is not None:
            out["sections"][name + "_count"] = count
    return out
