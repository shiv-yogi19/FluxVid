"""URL validation and SSRF protection."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from .errors import AppError

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = (None, 80, 443)


def _invalid() -> AppError:
    return AppError("invalid_url", "Enter a valid http or https link.")


def check_syntax(raw: str):
    """Return (clean_url, hostname, port) or raise AppError. No network access."""
    url = (raw or "").strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in url):
        raise _invalid()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise _invalid()
    try:
        port = parts.port
    except ValueError:
        raise _invalid() from None
    if port not in ALLOWED_PORTS:
        raise _invalid()
    return url, parts.hostname, port


def is_public_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.split("%")[0]).is_global
    except ValueError:
        return False


async def validate_url(raw: str) -> str:
    """Syntax check plus DNS resolution; every resolved address must be public."""
    url, host, port = check_syntax(raw)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise AppError("unresolvable", "That address could not be found.") from None
    if not infos or not all(is_public_address(info[4][0]) for info in infos):
        raise AppError("blocked_address", "That address is not allowed.")
    return url
