#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from sqlalchemy import or_, select


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.models import (  # noqa: E402
    GenerationRequest,
    MemoryEmbeddingTask,
    ModelCall,
)
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.services.operational_slos import (  # noqa: E402
    SLOPolicy,
    evaluate_slo_snapshot,
    http_snapshot,
    merge_alert_state,
    parse_access_metric_lines,
    percentile,
)


def _safe_base_url(value: str, allow_http_loopback: bool) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain credentials, query parameters, or fragments")
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if (
        allow_http_loopback
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        return value.rstrip("/")
    raise ValueError("SLO target must use HTTPS; HTTP requires explicit loopback approval")


def _readiness(
    base_url: str,
    timeout: float,
    tls_context: ssl.SSLContext | None = None,
) -> dict[str, Any]:
    request = Request(
        f"{base_url}/health/ready",
        headers={"Accept": "application/json", "User-Agent": "witscraft-slo-monitor/1"},
    )
    try:
        with urlopen(request, timeout=timeout, context=tls_context) as response:  # noqa: S310
            payload = json.load(response)
            return {
                "ready": response.status == 200 and payload.get("status") == "ready",
                "status_code": response.status,
            }
    except HTTPError as error:
        return {"ready": False, "status_code": error.code}
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return {"ready": False, "status_code": None}


def _access_events(path: Path, backup_count: int, since: datetime) -> list[dict[str, Any]]:
    lines: list[str] = []
    paths = [path, *(Path(f"{path}.{index}") for index in range(1, backup_count + 1))]
    for candidate in reversed(paths):
        if candidate.is_file():
            lines.extend(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
    return parse_access_metric_lines(lines, since=since)


def _aggregate_model_rows(rows: list[Any]) -> dict[str, Any]:
    calls = len(rows)
    succeeded = sum(row.status == "succeeded" for row in rows)
    latency = [float(row.latency_ms) for row in rows if row.latency_ms is not None]
    ttft = [
        float(row.first_token_latency_ms) for row in rows if row.first_token_latency_ms is not None
    ]
    return {
        "calls": calls,
        "failed": calls - succeeded,
        "fallback_attempts": sum((row.attempt or 1) > 1 for row in rows),
        "input_tokens": sum(row.input_tokens or 0 for row in rows),
        "latency_samples": len(latency),
        "output_tokens": sum(row.output_tokens or 0 for row in rows),
        "p95_latency_ms": percentile(latency, 0.95),
        "p95_ttft_ms": percentile(ttft, 0.95),
        "estimated_cost": round(sum(float(row.cost_estimate or 0) for row in rows), 8),
        "succeeded": succeeded,
        "success_rate": round(succeeded / calls, 6) if calls else None,
        "ttft_samples": len(ttft),
    }


async def _database_snapshot(
    *,
    since: datetime,
    now: datetime,
    policy: SLOPolicy,
    lease_seconds: int,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        model_rows = list(
            (
                await session.execute(
                    select(
                        ModelCall.status,
                        ModelCall.attempt,
                        ModelCall.input_tokens,
                        ModelCall.output_tokens,
                        ModelCall.latency_ms,
                        ModelCall.first_token_latency_ms,
                        ModelCall.cost_estimate,
                        ModelCall.provider,
                        ModelCall.model,
                        ModelCall.purpose,
                    ).where(
                        ModelCall.created_at >= since,
                        ModelCall.provider.in_(("openai", "deepinfra")),
                        ~ModelCall.model.ilike("%test%"),
                        or_(
                            ModelCall.call_type == "embedding",
                            ModelCall.response["dry_run"].as_boolean().is_(False),
                        ),
                    )
                )
            ).all()
        )
        by_purpose: dict[str, list[Any]] = defaultdict(list)
        by_model: dict[str, list[Any]] = defaultdict(list)
        for row in model_rows:
            by_purpose[row.purpose].append(row)
            by_model[f"{row.provider}:{row.model}"].append(row)
        model = _aggregate_model_rows(model_rows)
        model["by_purpose"] = {
            name: _aggregate_model_rows(rows) for name, rows in sorted(by_purpose.items())
        }
        model["by_model"] = {
            name: _aggregate_model_rows(rows) for name, rows in sorted(by_model.items())
        }

        generation_rows = list(
            (
                await session.execute(
                    select(
                        GenerationRequest.status,
                        GenerationRequest.created_at,
                        GenerationRequest.updated_at,
                    ).where(
                        or_(
                            GenerationRequest.created_at >= since,
                            GenerationRequest.status == "processing",
                        )
                    )
                )
            ).all()
        )
        generation_counts = Counter(row.status for row in generation_rows)
        processing_ages = [
            max(0.0, (now - (row.updated_at or row.created_at)).total_seconds())
            for row in generation_rows
            if row.status == "processing"
        ]

        task_rows = list(
            (
                await session.execute(
                    select(
                        MemoryEmbeddingTask.status,
                        MemoryEmbeddingTask.created_at,
                        MemoryEmbeddingTask.available_at,
                        MemoryEmbeddingTask.locked_at,
                    )
                )
            ).all()
        )
        task_counts = Counter(row.status for row in task_rows)
        queued_ages = [
            max(0.0, (now - row.created_at).total_seconds())
            for row in task_rows
            if row.status in {"pending", "retry"} and row.available_at <= now
        ]
        stale_before = now - timedelta(seconds=lease_seconds + 10)
        return {
            "database": {"available": True},
            "embedding": {
                "counts": dict(sorted(task_counts.items())),
                "dead": task_counts.get("dead", 0),
                "oldest_queue_age_seconds": round(max(queued_ages), 3) if queued_ages else None,
                "stale_running": sum(
                    row.status == "running"
                    and row.locked_at is not None
                    and row.locked_at < stale_before
                    for row in task_rows
                ),
            },
            "generation": {
                "counts": dict(sorted(generation_counts.items())),
                "oldest_processing_age_seconds": round(max(processing_ages), 3)
                if processing_ages
                else None,
                "stuck_processing": sum(
                    age > policy.maximum_generation_processing_age_seconds
                    for age in processing_ages
                ),
            },
            "model": model,
        }


def _backup_snapshot(directory: Path, now: datetime) -> dict[str, Any]:
    successful = [
        path
        for path in directory.glob("witscraft-*.dump.cms")
        if Path(f"{path}.sha256").is_file() and Path(f"{path}.json").is_file()
    ]
    if not successful:
        return {"newest_age_seconds": None, "successful_artifacts": 0}
    newest = max(successful, key=lambda path: path.stat().st_mtime)
    age = max(0.0, now.timestamp() - newest.stat().st_mtime)
    return {"newest_age_seconds": round(age, 3), "successful_artifacts": len(successful)}


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    policy = SLOPolicy(window_minutes=args.window_minutes)
    since = now - timedelta(minutes=policy.window_minutes)
    settings = get_settings()
    snapshot: dict[str, Any] = {
        "backup": _backup_snapshot(args.backup_dir, now),
        "http": http_snapshot(
            _access_events(args.api_log, settings.operational_metrics_log_backup_count, since)
        ),
        "observed_at": now.isoformat(),
        "readiness": _readiness(args.base_url, args.timeout, args.tls_context),
        "schema_version": "operational-slo-snapshot-v1",
        "window_started_at": since.isoformat(),
    }
    try:
        snapshot.update(
            await _database_snapshot(
                since=since,
                now=now,
                policy=policy,
                lease_seconds=settings.memory_embedding_worker_lease_seconds,
            )
        )
    except Exception:
        snapshot.update(
            {
                "database": {"available": False},
                "embedding": {},
                "generation": {},
                "model": {},
            }
        )
    evaluation = evaluate_slo_snapshot(snapshot, policy)
    state = merge_alert_state(_load_state(args.state_file), evaluation["alerts"], observed_at=now)
    report = {"evaluation": evaluation, "snapshot": snapshot, "state": state}
    _write_private_json(args.state_file, state)
    if args.report_file:
        _write_private_json(args.report_file, report)
    await engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate metadata-only Witscraft production SLOs and alert state"
    )
    parser.add_argument("base_url")
    parser.add_argument("--api-log", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--window-minutes", type=int, default=30, choices=range(5, 1441))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--allow-http-loopback", action="store_true")
    parser.add_argument(
        "--ca-file",
        type=Path,
        help="Trust this private CA/certificate for an isolated HTTPS staging target.",
    )
    args = parser.parse_args()
    try:
        args.base_url = _safe_base_url(args.base_url, args.allow_http_loopback)
        if args.ca_file is not None:
            if not args.ca_file.is_file():
                raise ValueError("CA file does not exist")
            args.tls_context = ssl.create_default_context(cafile=args.ca_file)
        else:
            args.tls_context = None
        report = asyncio.run(_run(args))
    except Exception as error:
        print(json.dumps({"event": "slo_monitor_error", "error": type(error).__name__}))
        return 3
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["evaluation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
