"""Strict, deterministic declassification of public IPv4 IOCs from evidence."""

from __future__ import annotations

import ipaddress
import re

MAX_SOURCE_CHARS = 1_000_000
MAX_IOCS = 20
IPV4_CANDIDATE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


def extract_public_ipv4_iocs(source: str) -> tuple[str, ...]:
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError("INVALID_IOC_SOURCE")
    addresses: set[str] = set()
    for match in IPV4_CANDIDATE.finditer(source):
        try:
            address = ipaddress.IPv4Address(match.group())
        except ipaddress.AddressValueError:
            continue
        if address.is_global and not address.is_multicast and not address.is_reserved:
            addresses.add(str(address))
            if len(addresses) > MAX_IOCS:
                raise ValueError("IOC_LIMIT_EXCEEDED")
    return tuple(sorted(addresses, key=ipaddress.IPv4Address))


def render_public_ipv4_iocs(addresses: tuple[str, ...]) -> str:
    if not addresses:
        raise ValueError("NO_PUBLIC_IOCS")
    return "PUBLIC_IPV4_IOCS\n" + "\n".join(addresses)
