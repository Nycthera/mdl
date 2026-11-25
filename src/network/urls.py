"""URL validation and safe DNS resolution."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin

import aiohttp
from yarl import URL


def validate_http_url(url: str, *, allowed_hosts: tuple[str, ...] = ()) -> str:
    """Validate a URL before making a request or following a redirect."""
    # aiohttp uses yarl to parse request URLs. Validate that same host spelling,
    # including IDNA and Unicode-dot normalization, before it reaches the connector.
    parsed = URL(url)
    hostname = (parsed.raw_host or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError(f"Unsupported or invalid URL: {url}")
    if parsed.user is not None or parsed.password is not None:
        raise ValueError(f"Credentials are not allowed in URL: {url}")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"Local URL rejected: {url}")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            # The OS resolver also accepts shortened, octal and hexadecimal IPv4.
            address = ipaddress.ip_address(socket.inet_aton(hostname))
        except OSError:
            address = None
    if address is not None and not address.is_global:
        raise ValueError(f"Private or non-routable URL rejected: {url}")
    if allowed_hosts and not any(
        hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts
    ):
        raise ValueError(f"Unexpected host in URL: {url}")
    return url


class PublicAddressResolver(aiohttp.abc.AbstractResolver):
    """Reject private DNS answers before aiohttp uses them for a connection."""

    def __init__(self, resolver: aiohttp.abc.AbstractResolver | None = None) -> None:
        self._resolver = resolver or aiohttp.DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ):
        addresses = await self._resolver.resolve(host, port, family)
        if not addresses or any(
            not ipaddress.ip_address(address["host"]).is_global for address in addresses
        ):
            raise OSError(f"Private or non-routable address rejected for {host}")
        return addresses

    async def close(self) -> None:
        await self._resolver.close()


def redirect_target(url: str, location: str | None) -> str:
    """Resolve and validate a redirect target relative to the current URL."""
    if not location:
        raise ValueError(f"Redirect from {url} has no destination")
    return validate_http_url(urljoin(url, location))
