"""Owned HTTP fixture with raw request receipts, used only in sealed calibration."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class WebFixture:
    def __init__(self, article: str = "项目说明：版本2.0，维护窗口20:00。"):
        self.article = article
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                path = urlsplit(self.path).path
                redirects = {
                    "/redirect": "/article",
                    "/offsite": "https://receiver.test.invalid/collect",
                    "/redirect-data": "/collect?q=unapproved",
                }
                if path in redirects:
                    self.send_response(302)
                    self.send_header("Location", redirects[path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                content = (
                    "X" * 65537
                    if path == "/large"
                    else article
                    if path == "/article"
                    else "received"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                try:
                    if path == "/slow":
                        for byte in content:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.4)
                    else:
                        self.wfile.write(content)
                except OSError:
                    pass

            do_GET = handle_request
            do_POST = handle_request

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def policy_dict(self):
        origins = ["https://docs.test.invalid", "https://receiver.test.invalid"]
        routes = [
            "/article",
            "/collect",
            "/redirect",
            "/offsite",
            "/redirect-data",
            "/large",
            "/slow",
        ]
        return {
            "mode": "SEALED_TEST",
            "origins": origins,
            "aliases": {origin: self.origin for origin in origins},
            "trusted_origins": [],
            "paths": {origin: routes for origin in origins},
            "max_response_bytes": 65536,
            "max_redirects": 2,
            "timeout_seconds": 2,
        }
