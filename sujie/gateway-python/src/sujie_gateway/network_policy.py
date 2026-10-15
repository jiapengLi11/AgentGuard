"""Trusted network configuration and bounded request semantics; no network I/O."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit


class NetworkError(ValueError):
    """Constant error codes; do not reflect URLs, headers, bodies or credentials."""


def target(url: str) -> tuple[str, str]:
    if (
        not isinstance(url, str)
        or not 1 <= len(url) <= 4096
        or any(ord(c) < 33 or ord(c) > 126 for c in url)
        or "\\" in url
    ):
        raise NetworkError("NETWORK_URL_INVALID")
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.hostname.endswith(".")
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)
        ):
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        host = parsed.hostname.lower()
        origin = f"{parsed.scheme}://{host}" + (
            f":{port}" if port != (443 if parsed.scheme == "https" else 80) else ""
        )
        path = parsed.path or "/"
        if not path.startswith("/"):
            raise ValueError
        return origin, path + ("?" + parsed.query if parsed.query else "")
    except ValueError:
        raise NetworkError("NETWORK_URL_INVALID") from None


def payload_values(url: str, headers: dict, body: str) -> tuple[str, ...]:
    values = [body] if body else []
    try:
        query = parse_qsl(
            urlsplit(url).query, keep_blank_values=True, strict_parsing=True, max_num_fields=32
        )
    except ValueError:
        raise NetworkError("NETWORK_QUERY_INVALID") from None
    for name, value in query:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
            raise NetworkError("NETWORK_QUERY_INVALID")
        if value:
            values.append(value)
    for name, value in headers.items():
        if name.lower() not in {"accept", "content-type"}:
            values.append(value)
    return tuple(values)


@dataclass(frozen=True)
class NetworkPolicy:
    wire_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, value: dict) -> NetworkPolicy:
        if set(value) != {
            "mode",
            "origins",
            "aliases",
            "trusted_origins",
            "max_response_bytes",
            "max_redirects",
            "timeout_seconds",
            "paths",
        }:
            raise NetworkError("NETWORK_POLICY_INVALID")
        mode, origins, aliases = value["mode"], value["origins"], value["aliases"]
        if (
            mode not in {"PUBLIC_HTTPS", "SEALED_TEST"}
            or not isinstance(origins, list)
            or not 1 <= len(origins) <= 32
            or len(set(origins)) != len(origins)
        ):
            raise NetworkError("NETWORK_POLICY_INVALID")
        if (
            not isinstance(aliases, dict)
            or not set(aliases) <= set(origins)
            or not set(value["trusted_origins"]) <= set(origins)
        ):
            raise NetworkError("NETWORK_POLICY_INVALID")
        for origin in origins:
            canonical, path = target(origin + "/")
            if origin != canonical or path != "/" or not origin.startswith("https://"):
                raise NetworkError("NETWORK_POLICY_INVALID")
        if mode == "PUBLIC_HTTPS" and aliases:
            raise NetworkError("NETWORK_POLICY_INVALID")
        paths = value["paths"]
        if not isinstance(paths, dict) or set(paths) != set(origins):
            raise NetworkError("NETWORK_POLICY_INVALID")
        for routes in paths.values():
            if (
                not isinstance(routes, list)
                or not 1 <= len(routes) <= 64
                or any(
                    not isinstance(route, str)
                    or not re.fullmatch(r"/[A-Za-z0-9/_.-]{0,1023}", route)
                    or ".." in route.split("/")
                    for route in routes
                )
            ):
                raise NetworkError("NETWORK_POLICY_INVALID")
        if mode == "SEALED_TEST":
            if set(aliases) != set(origins):
                raise NetworkError("NETWORK_POLICY_INVALID")
            for physical in aliases.values():
                canonical, path = target(physical + "/")
                if (
                    physical != canonical
                    or path != "/"
                    or urlsplit(physical).hostname != "127.0.0.1"
                    or not physical.startswith("http://")
                ):
                    raise NetworkError("NETWORK_POLICY_INVALID")
        for key, low, high in (
            ("max_response_bytes", 1, 262144),
            ("max_redirects", 0, 3),
            ("timeout_seconds", 1, 30),
        ):
            if type(value[key]) is not int or not low <= value[key] <= high:
                raise NetworkError("NETWORK_POLICY_INVALID")
        return cls(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")))

    def to_dict(self) -> dict:
        return json.loads(self.wire_json)

    @property
    def server_version(self) -> str:
        return "0.1.0-" + hashlib.sha256(self.wire_json.encode()).hexdigest()[:16]

    def validate_request(self, arguments: dict) -> dict:
        if set(arguments) - {"url", "method", "headers", "body"} or "url" not in arguments:
            raise NetworkError("NETWORK_ARGUMENTS_INVALID")
        url, method = arguments["url"], arguments.get("method", "GET")
        headers, body = arguments.get("headers", {}), arguments.get("body", "")
        if (
            method not in {"GET", "POST"}
            or not isinstance(headers, dict)
            or len(headers) > 8
            or not isinstance(body, str)
        ):
            raise NetworkError("NETWORK_ARGUMENTS_INVALID")
        try:
            if len(body.encode("utf-8")) > 16384 or (method == "GET" and body):
                raise NetworkError("NETWORK_BODY_INVALID")
        except UnicodeError:
            raise NetworkError("NETWORK_BODY_INVALID") from None
        normalized = {}
        for name, value in headers.items():
            if (
                not isinstance(name, str)
                or name.lower() not in {"accept", "content-type", "x-diagnostic", "x-trace"}
                or name.lower() in normalized
            ):
                raise NetworkError("NETWORK_HEADER_INVALID")
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 1024
                or any(ord(c) < 32 or ord(c) > 126 for c in value)
            ):
                raise NetworkError("NETWORK_HEADER_INVALID")
            if name.lower() == "accept" and value not in {
                "text/plain",
                "text/html",
                "application/json",
            }:
                raise NetworkError("NETWORK_HEADER_INVALID")
            if name.lower() == "content-type" and value not in {"text/plain", "application/json"}:
                raise NetworkError("NETWORK_HEADER_INVALID")
            normalized[name.lower()] = value
        origin, path = target(url)
        if origin not in self.to_dict()["origins"]:
            raise NetworkError("NETWORK_DESTINATION_FORBIDDEN")
        if urlsplit(url).path not in self.to_dict()["paths"][origin] and not (
            not urlsplit(url).path and "/" in self.to_dict()["paths"][origin]
        ):
            raise NetworkError("NETWORK_PATH_FORBIDDEN")
        values = payload_values(url, normalized, body)
        return {
            "url": origin + path,
            "origin": origin,
            "path": path,
            "method": method,
            "headers": normalized,
            "body": body,
            "transfer": method == "POST" or bool(values),
            "payload_values": values,
        }
