"""Reading other sites: the pools' APIs, DMD Stats, GitHub. Only HTTPS, only public addresses, a
size limit and a time limit, and no redirect to another site.

The addresses come from DebitMyData's pool list (pools-info.json on GitHub): a wrong one must not
make this server read anything on its own network, so names that point to a private address
(this server, a LAN, a cloud's metadata address) are refused.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from dmdmining import __version__

USER_AGENT = f"DebitMyData-Mining/{__version__} (+https://mining.debitmydata.io)"
MAX_BYTES = 4_000_000
TIMEOUT = 15
#: The tests' stand-in servers (http on this machine allowed).
TEST_HOSTS: set[str] = set()


class FetchError(Exception):
    pass


def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


def check_url(url: str) -> urllib.parse.SplitResult:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise FetchError("not an address") from exc
    host = (parts.hostname or "").lower()
    if parts.netloc.lower() in TEST_HOSTS or host in TEST_HOSTS:
        return parts
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise FetchError("only https addresses")
    if not _public(host):
        raise FetchError(f"{host} is not a public address")
    return parts


class _SameSite(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only on the same site (http to https, a trailing slash)."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (new.hostname or "").lower() != (old.hostname or "").lower():
            raise FetchError(f"redirected to another site ({new.hostname})")
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameSite)


def get(url: str, timeout: float = TIMEOUT, limit: int = MAX_BYTES) -> bytes:
    check_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/csv, image/svg+xml, */*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with _opener.open(request, timeout=timeout) as response:
            body = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(str(reason)[:200]) from exc
    if len(body) > limit:
        raise FetchError("the answer is too large")
    return body


def get_json(url: str, timeout: float = TIMEOUT, limit: int = MAX_BYTES) -> Any:
    body = get(url, timeout, limit)
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FetchError("the answer is not JSON") from exc
