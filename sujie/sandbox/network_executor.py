"""Bounded direct HTTP transport, with public DNS pinning or explicit test aliases."""

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as DNSTimeout
from urllib.parse import urljoin, urlsplit

from sujie_gateway.network_policy import NetworkError, NetworkPolicy, target

DNS_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sujie-dns")
DNS_SLOTS = threading.BoundedSemaphore(2)


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address, self.secure = address, secure

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        if self.secure:
            try:
                self.sock = ssl.create_default_context().wrap_socket(
                    self.sock, server_hostname=self.host
                )
            except BaseException:
                self.sock.close()
                raise


def resolve_public(host: str, port: int, timeout: float = 5) -> str:
    if not DNS_SLOTS.acquire(blocking=False):
        raise NetworkError("NETWORK_DNS_BUSY")
    future = DNS_WORKERS.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    future.add_done_callback(lambda _: DNS_SLOTS.release())
    try:
        addresses = {row[4][0] for row in future.result(timeout=timeout)}
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise NetworkError("NETWORK_PRIVATE_ADDRESS_FORBIDDEN")
        return sorted(addresses)[0]
    except NetworkError:
        raise
    except DNSTimeout:
        raise NetworkError("NETWORK_DNS_TIMEOUT") from None
    except (OSError, ValueError):
        raise NetworkError("NETWORK_DNS_FAILED") from None


def fetch(policy: NetworkPolicy, arguments: dict) -> dict:
    request = policy.validate_request(arguments)
    config = policy.to_dict()
    deadline = time.monotonic() + config["timeout_seconds"]
    chain = []
    for hop in range(config["max_redirects"] + 1):
        request = policy.validate_request(
            {key: request[key] for key in ("url", "method", "headers", "body")}
        )
        origin = request["origin"]
        physical = config["aliases"].get(origin, origin)
        endpoint = urlsplit(physical)
        port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NetworkError("NETWORK_TIMEOUT")
        address = (
            "127.0.0.1"
            if config["mode"] == "SEALED_TEST"
            else resolve_public(endpoint.hostname, port, remaining)
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NetworkError("NETWORK_TIMEOUT")
        connection = PinnedConnection(
            endpoint.hostname, port, address, endpoint.scheme == "https", remaining
        )

        transport_socket = None

        def abort():
            active_socket = transport_socket or connection.sock
            if active_socket is not None:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        deadline_timer = threading.Timer(remaining, abort)
        deadline_timer.daemon = True
        deadline_timer.start()
        try:
            connection.request(
                request["method"],
                request["path"],
                body=request["body"].encode() or None,
                headers={"Host": urlsplit(origin).netloc, **request["headers"]},
            )
            transport_socket = connection.sock
            if time.monotonic() >= deadline:
                raise NetworkError("NETWORK_TIMEOUT")
            response = connection.getresponse()
            if time.monotonic() >= deadline:
                raise NetworkError("NETWORK_TIMEOUT")
            chain.append(origin)
            if response.status in {301, 302, 303, 307, 308}:
                if request["method"] != "GET":
                    raise NetworkError("NETWORK_REDIRECT_ON_MUTATION")
                if hop == config["max_redirects"]:
                    raise NetworkError("NETWORK_REDIRECT_LIMIT")
                location = response.getheader("Location")
                if not location:
                    raise NetworkError("NETWORK_REDIRECT_INVALID")
                redirected = urljoin(request["url"], location)
                next_origin, _ = target(redirected)
                if next_origin != origin:
                    raise NetworkError("NETWORK_CROSS_ORIGIN_REDIRECT_FORBIDDEN")
                next_request = policy.validate_request(
                    {"url": redirected, "method": "GET", "headers": request["headers"], "body": ""}
                )
                if request["transfer"] or next_request["transfer"]:
                    raise NetworkError("NETWORK_REDIRECT_PAYLOAD_CHANGED")
                request["url"] = redirected
                continue
            if response.status != 200:
                raise NetworkError("NETWORK_HTTP_STATUS_FAILED")
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NetworkError("NETWORK_TIMEOUT")
                if response.isclosed():
                    break
                transport_socket.settimeout(remaining)
                chunk = response.read1(min(8192, config["max_response_bytes"] + 1 - size))
                # Deadline shutdown can wake a blocked read as EOF, not OSError.
                if time.monotonic() >= deadline:
                    raise NetworkError("NETWORK_TIMEOUT")
                if not chunk:
                    if response.length:
                        raise NetworkError("NETWORK_RESPONSE_TRUNCATED")
                    break
                size += len(chunk)
                if size > config["max_response_bytes"]:
                    raise NetworkError("NETWORK_RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            content = b"".join(chunks).decode("utf-8")
            return {
                "resource": origin + "/",
                "content": content,
                "status_code": 200,
                "bytes_read": size,
                "redirect_origins": chain,
            }
        except NetworkError:
            raise
        except (OSError, http.client.HTTPException, UnicodeError):
            raise NetworkError(
                "NETWORK_TIMEOUT" if time.monotonic() >= deadline else "NETWORK_TRANSPORT_FAILED"
            ) from None
        finally:
            deadline_timer.cancel()
            connection.close()
    raise NetworkError("NETWORK_REDIRECT_LIMIT")
