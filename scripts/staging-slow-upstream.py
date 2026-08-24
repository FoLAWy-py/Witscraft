#!/usr/bin/env python3
"""Serve one deliberately slow loopback response for the staging 504 contract check."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class SlowHandler(BaseHTTPRequestHandler):
    delay_seconds = 3.0

    def do_GET(self) -> None:  # noqa: N802
        time.sleep(self.delay_seconds)
        payload = json.dumps({"status": "late"}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(LOOPBACK_HOSTS))
    parser.add_argument("--port", type=int, required=True, choices=range(1024, 65536))
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if not 1.1 <= args.delay <= 10:
        parser.error("--delay must be between 1.1 and 10 seconds")

    SlowHandler.delay_seconds = args.delay
    server = HTTPServer((args.host, args.port), SlowHandler)
    args.ready_file.write_text("ready\n", encoding="utf-8")
    args.ready_file.chmod(0o600)
    try:
        server.handle_request()
    finally:
        server.server_close()
        args.ready_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
