#!/usr/bin/env python3
"""Run non-mutating release smoke checks against a deployed base URL."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def _safe_base_url(value: str, allow_http_loopback: bool) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain credentials, query parameters, or fragments")
    if parsed.scheme == "https" and parsed.netloc:
        return urlunsplit(parsed)
    if (
        allow_http_loopback
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        return urlunsplit(parsed)
    raise ValueError("Smoke target must use HTTPS; HTTP is allowed only for explicit loopback checks")


def _get_json(url: str, timeout: float, tls_context: ssl.SSLContext | None = None) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "witscraft-smoke/1"})
    with urlopen(request, timeout=timeout, context=tls_context) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        content_type = response.headers.get_content_type()
        if content_type != "application/json":
            raise RuntimeError(f"unexpected content type {content_type}")
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--allow-http-loopback", action="store_true")
    parser.add_argument(
        "--ca-file",
        type=Path,
        help="Trust this private CA/certificate for an isolated HTTPS staging target.",
    )
    args = parser.parse_args()
    try:
        base_url = _safe_base_url(args.base_url, args.allow_http_loopback)
        manifest = json.loads(args.manifest.read_text())
        tls_context = None
        if args.ca_file is not None:
            if not args.ca_file.is_file():
                raise ValueError("CA file does not exist")
            tls_context = ssl.create_default_context(cafile=args.ca_file)
        live = _get_json(f"{base_url}/health/live", args.timeout, tls_context)
        ready = _get_json(f"{base_url}/health/ready", args.timeout, tls_context)
        if live.get("status") != "alive":
            raise RuntimeError("liveness response is not alive")
        if ready.get("status") != "ready":
            raise RuntimeError("readiness response is not ready")
        expected = sorted(manifest["migration_heads"])
        if sorted(ready.get("migration_revisions", [])) != expected:
            raise RuntimeError("deployed migration revision does not match the release manifest")
        if sorted(ready.get("expected_migration_revisions", [])) != expected:
            raise RuntimeError("application migration head does not match the release manifest")
    except (OSError, ValueError, KeyError, RuntimeError, HTTPError, URLError, json.JSONDecodeError) as error:
        print(f"Release smoke failed: {error}", file=sys.stderr)
        return 1
    print("Release smoke passed: live, ready, and migration revision match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
