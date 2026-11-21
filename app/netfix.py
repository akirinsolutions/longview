"""Resilient name resolution for the whole app.

Some networks (notably this machine's, right now) hand the host *no*
DNS servers at all: every name lookup in the system fails, even though
plain internet egress works fine. ``install()`` puts a fallback in front
of ``socket.getaddrinfo``: try the system resolver first, and only when
it fails, ask a public DNS-over-HTTPS endpoint.

The DoH endpoints are called by **IP literal** (1.1.1.1, 8.8.8.8), so
the fallback needs no working DNS to work itself — it is the boot
strapping step. Nothing is sent to those endpoints except a hostname
and an A/AAAA question.

Set ``LONGVIEW_DNS_FALLBACK=0`` to disable the install (for
debugging; the legacy ``PROOF_DNS_FALLBACK`` is read as a fallback).
On machines with a normal resolver the fallback never fires and the
behaviour is bit-for-bit the same as before.
"""
from __future__ import annotations

import os
import socket
import threading

_installed = False
_install_lock = threading.Lock()


def _doh_lookup(name: str, qtype: str = "A") -> list[str]:
    """Resolve one name against public DoH endpoints, by IP literal.

    Returns the list of answers (may be empty). Never raises.
    """
    if not name:
        return []
    try:
        import ipaddress
        ipaddress.ip_address(name)
        return []  # an IP literal needs no lookup
    except ValueError:
        pass
    import httpx  # already a project dependency (see risk.py)

    endpoints = [
        ("https://1.1.1.1", "/dns-query?name=%s&type=" + qtype),
        ("https://8.8.8.8", "/resolve?name=%s&type=" + qtype),
    ]
    for base, path in endpoints:
        try:
            r = httpx.get(
                base + (path % name),
                headers={"Accept": "application/dns-json"},
                timeout=6.0,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            want = 1 if qtype == "A" else 28
            answers = [a["data"] for a in data.get("Answer", [])
                       if a.get("type") == want and a.get("data")]
            if answers:
                # Keep first-seen order, drop duplicates.
                seen: set[str] = set()
                return [a for a in answers if not (a in seen or seen.add(a))]
        except Exception:
            continue
    return []


def _fallback_getaddrinfo(host, port, *args, **kwargs):
    """getaddrinfo with a DoH fallback for the no-nameserver case.

    Mirrors the stdlib call shape (``family``, ``type``, ``proto``,
    ``flags`` positional or keyword). When the system lookup raises
    ``gaierror`` for a real hostname, resolve over DoH and hand back
    the same tuple shape ``socket.create_connection`` expects.
    """
    global _ORIG_GETADDRINFO
    try:
        return _ORIG_GETADDRINFO(host, port, *args, **kwargs)
    except socket.gaierror:
        pass
    if not isinstance(host, str) or "." not in host:
        # Numeric or already-absolute: let the original error stand.
        return _ORIG_GETADDRINFO(host, port, *args, **kwargs)
    family = args[0] if len(args) > 0 else kwargs.get("family", 0)
    want6 = family == socket.AF_INET6
    qtype = "AAAA" if want6 else ("A" if family in (0, socket.AF_INET) else "A")
    if family == 0:
        # AF_UNSPEC: try A first; if nothing, try AAAA.
        ips = _doh_lookup(host, "A") or _doh_lookup(host, "AAAA")
    else:
        ips = _doh_lookup(host, qtype)
    if not ips:
        raise socket.gaierror("no DNS servers are configured on this machine "
                              "and the fallback lookup found nothing")
    out = []
    for ip in ips:
        is6 = ":" in ip
        fam = socket.AF_INET6 if is6 else socket.AF_INET
        if want6 and not is6:
            continue
        out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port)))
    if not out:
        raise socket.gaierror("no DNS servers are configured on this machine")
    return out


_ORIG_GETADDRINFO = socket.getaddrinfo


def install() -> bool:
    """Patch ``socket.getaddrinfo`` once. Idempotent.

    Returns True when the fallback is active.
    """
    global _installed
    flag = os.environ.get("LONGVIEW_DNS_FALLBACK",
                          os.environ.get("PROOF_DNS_FALLBACK", "1"))
    if flag == "0":
        return False
    with _install_lock:
        if _installed:
            return True
        socket.getaddrinfo = _fallback_getaddrinfo
        _installed = True
        return True


def is_active() -> bool:
    return _installed
