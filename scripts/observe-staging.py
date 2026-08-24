#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = (ROOT / ".runtime").resolve()


def _safe_https_url(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Observation target must be an HTTPS URL without credentials or query data")
    return value.rstrip("/")


def _probe(url: str, context: ssl.SSLContext, timeout: float) -> tuple[int | None, float]:
    started = time.monotonic()
    try:
        with urlopen(  # noqa: S310 - URL is constrained to operator-supplied HTTPS.
            Request(url, headers={"User-Agent": "witscraft-staging-observer/1"}),
            timeout=timeout,
            context=context,
        ) as response:
            response.read(64 * 1024)
            return response.status, (time.monotonic() - started) * 1000
    except HTTPError as error:
        return error.code, (time.monotonic() - started) * 1000
    except (OSError, URLError, ValueError):
        return None, (time.monotonic() - started) * 1000


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return round(ordered[index], 2)


def _write_private(path: Path, payload: dict) -> None:
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(RUNTIME_ROOT):
        raise ValueError("Observation output must remain inside the ignored .runtime directory")
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{resolved.name}.", dir=resolved.parent)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary, resolved)
    except BaseException:
        try:
            os.close(handle)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe an isolated HTTPS staging candidate")
    parser.add_argument("base_url", type=_safe_https_url)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=int, default=30, choices=range(5, 61))
    parser.add_argument("--interval-seconds", type=int, default=30, choices=range(10, 301))
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if not args.ca_file.is_file():
        parser.error("--ca-file must be a readable certificate")

    context = ssl.create_default_context(cafile=args.ca_file)
    requested_seconds = args.minutes * 60
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    samples: list[dict] = []
    while True:
        sample_started = time.monotonic()
        ready_status, ready_ms = _probe(
            f"{args.base_url}/health/ready", context, args.timeout
        )
        ui_status, ui_ms = _probe(args.base_url, context, args.timeout)
        samples.append(
            {
                "elapsed_seconds": round(sample_started - started, 2),
                "readiness_status": ready_status,
                "readiness_latency_ms": round(ready_ms, 2),
                "ui_status": ui_status,
                "ui_latency_ms": round(ui_ms, 2),
            }
        )
        elapsed = time.monotonic() - started
        if elapsed >= requested_seconds:
            break
        time.sleep(min(args.interval_seconds, requested_seconds - elapsed))

    observed_seconds = time.monotonic() - started
    readiness_latencies = [sample["readiness_latency_ms"] for sample in samples]
    ui_latencies = [sample["ui_latency_ms"] for sample in samples]
    readiness_failures = sum(sample["readiness_status"] != 200 for sample in samples)
    ui_failures = sum(sample["ui_status"] != 200 for sample in samples)
    deployment_revision = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    worktree_clean = not bool(
        subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    report = {
        "schema_version": "staging-observation-v1",
        "deployment_revision": deployment_revision,
        "worktree_clean": worktree_clean,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": requested_seconds,
        "observed_seconds": round(observed_seconds, 2),
        "sample_count": len(samples),
        "readiness_failures": readiness_failures,
        "ui_failures": ui_failures,
        "readiness_p95_ms": _percentile(readiness_latencies, 0.95),
        "ui_p95_ms": _percentile(ui_latencies, 0.95),
        "passed": (
            observed_seconds >= requested_seconds
            and readiness_failures == 0
            and ui_failures == 0
            and worktree_clean
        ),
        "samples": samples,
    }
    _write_private(args.output, report)
    print(
        "Staging observation completed: "
        f"samples={len(samples)} readiness_failures={readiness_failures} "
        f"ui_failures={ui_failures} passed={report['passed']}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
