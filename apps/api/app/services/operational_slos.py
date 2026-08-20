from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.operational_logging import ACCESS_METRIC_MARKER


@dataclass(frozen=True)
class SLOPolicy:
    version: str = "production-slo-v1"
    window_minutes: int = 30
    minimum_http_samples: int = 20
    minimum_model_samples: int = 5
    maximum_http_5xx_rate: float = 0.01
    maximum_http_p95_ms: float = 2_500.0
    minimum_model_success_rate: float = 0.95
    maximum_model_p95_ms: float = 60_000.0
    maximum_model_ttft_p95_ms: float = 15_000.0
    maximum_generation_processing_age_seconds: float = 600.0
    maximum_embedding_queue_age_seconds: float = 900.0
    maximum_backup_age_seconds: float = 93_600.0

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    position = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[position], 3)


def parse_access_metric_lines(lines: Iterable[str], *, since: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in lines:
        marker_position = line.find(ACCESS_METRIC_MARKER)
        if marker_position < 0:
            continue
        try:
            payload = json.loads(line[marker_position + len(ACCESS_METRIC_MARKER) :])
            observed_at = datetime.fromisoformat(str(payload["observed_at"]))
            if observed_at.tzinfo is None:
                continue
            route = str(payload["route"])
            method = str(payload["method"])
            status_code = int(payload["status_code"])
            duration_ms = float(payload["duration_ms"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            payload.get("event") != "http_request"
            or observed_at < since
            or not route.startswith("/")
            and route != "unmatched"
            or not 100 <= status_code <= 599
            or duration_ms < 0
        ):
            continue
        events.append(
            {
                "duration_ms": duration_ms,
                "method": method[:12],
                "observed_at": observed_at,
                "route": route[:240],
                "status_code": status_code,
            }
        )
    return events


def http_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        event
        for event in events
        if event["method"] != "OPTIONS"
        and not event["route"].startswith("/health")
        and not event["route"].startswith("/api/admin")
    ]
    latency_eligible = [event for event in eligible if event["route"] != "/api/chat/stream"]
    failures = sum(event["status_code"] >= 500 for event in eligible)
    by_route: dict[str, dict[str, int]] = {}
    for event in eligible:
        bucket = by_route.setdefault(event["route"], {"requests": 0, "server_errors": 0})
        bucket["requests"] += 1
        bucket["server_errors"] += int(event["status_code"] >= 500)
    return {
        "requests": len(eligible),
        "server_errors": failures,
        "server_error_rate": round(failures / len(eligible), 6) if eligible else None,
        "non_stream_latency_samples": len(latency_eligible),
        "non_stream_p95_ms": percentile((event["duration_ms"] for event in latency_eligible), 0.95),
        "by_route": dict(sorted(by_route.items())),
    }


def _alert(
    code: str,
    *,
    value: float | int | str | None,
    threshold: float | int | str,
    severity: str = "critical",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "threshold": threshold,
        "value": value,
    }


def evaluate_slo_snapshot(snapshot: dict[str, Any], policy: SLOPolicy) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    insufficient_samples: list[str] = []
    if not snapshot.get("readiness", {}).get("ready", False):
        alerts.append(_alert("readiness_failed", value="not_ready", threshold="ready"))
    if not snapshot.get("database", {}).get("available", False):
        alerts.append(_alert("metrics_database_failed", value="unavailable", threshold="available"))

    http = snapshot.get("http", {})
    http_samples = int(http.get("requests") or 0)
    if http_samples < policy.minimum_http_samples:
        insufficient_samples.append("http_availability")
    elif float(http.get("server_error_rate") or 0) > policy.maximum_http_5xx_rate:
        alerts.append(
            _alert(
                "http_5xx_rate_high",
                value=http.get("server_error_rate"),
                threshold=policy.maximum_http_5xx_rate,
            )
        )
    latency_samples = int(http.get("non_stream_latency_samples") or 0)
    if latency_samples < policy.minimum_http_samples:
        insufficient_samples.append("http_latency")
    elif float(http.get("non_stream_p95_ms") or 0) > policy.maximum_http_p95_ms:
        alerts.append(
            _alert(
                "http_p95_high",
                value=http.get("non_stream_p95_ms"),
                threshold=policy.maximum_http_p95_ms,
                severity="warning",
            )
        )

    model = snapshot.get("model", {})
    model_samples = int(model.get("calls") or 0)
    if model_samples < policy.minimum_model_samples:
        insufficient_samples.append("model_success")
    else:
        if float(model.get("success_rate") or 0) < policy.minimum_model_success_rate:
            alerts.append(
                _alert(
                    "model_success_rate_low",
                    value=model.get("success_rate"),
                    threshold=policy.minimum_model_success_rate,
                )
            )
        if int(model.get("latency_samples") or 0) < policy.minimum_model_samples:
            insufficient_samples.append("model_latency")
        elif (
            model.get("p95_latency_ms") is not None
            and float(model["p95_latency_ms"]) > policy.maximum_model_p95_ms
        ):
            alerts.append(
                _alert(
                    "model_p95_high",
                    value=model["p95_latency_ms"],
                    threshold=policy.maximum_model_p95_ms,
                    severity="warning",
                )
            )
        if int(model.get("ttft_samples") or 0) < policy.minimum_model_samples:
            insufficient_samples.append("model_ttft")
        elif (
            model.get("p95_ttft_ms") is not None
            and float(model["p95_ttft_ms"]) > policy.maximum_model_ttft_p95_ms
        ):
            alerts.append(
                _alert(
                    "model_ttft_p95_high",
                    value=model["p95_ttft_ms"],
                    threshold=policy.maximum_model_ttft_p95_ms,
                    severity="warning",
                )
            )

    generation = snapshot.get("generation", {})
    if int(generation.get("stuck_processing") or 0) > 0:
        alerts.append(
            _alert(
                "generation_processing_stuck",
                value=generation.get("oldest_processing_age_seconds"),
                threshold=policy.maximum_generation_processing_age_seconds,
            )
        )
    embedding = snapshot.get("embedding", {})
    if int(embedding.get("dead") or 0) > 0:
        alerts.append(_alert("embedding_dead_letters", value=embedding["dead"], threshold=0))
    if int(embedding.get("stale_running") or 0) > 0:
        alerts.append(
            _alert("embedding_stale_leases", value=embedding["stale_running"], threshold=0)
        )
    queue_age = embedding.get("oldest_queue_age_seconds")
    if queue_age is not None and float(queue_age) > policy.maximum_embedding_queue_age_seconds:
        alerts.append(
            _alert(
                "embedding_queue_old",
                value=queue_age,
                threshold=policy.maximum_embedding_queue_age_seconds,
            )
        )
    backup = snapshot.get("backup", {})
    backup_age = backup.get("newest_age_seconds")
    if backup_age is None or float(backup_age) > policy.maximum_backup_age_seconds:
        alerts.append(
            _alert(
                "backup_missing_or_old",
                value=backup_age,
                threshold=policy.maximum_backup_age_seconds,
            )
        )
    return {
        "alerts": sorted(alerts, key=lambda alert: alert["code"]),
        "insufficient_samples": sorted(set(insufficient_samples)),
        "passed": not alerts,
        "policy": policy.public_dict(),
    }


def merge_alert_state(
    previous: dict[str, Any] | None,
    alerts: list[dict[str, Any]],
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    timestamp = observed_at.astimezone(timezone.utc).isoformat()
    previous_by_code = {
        item.get("code"): item
        for item in (previous or {}).get("active_alerts", [])
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    }
    active = []
    for alert in alerts:
        prior = previous_by_code.get(alert["code"], {})
        active.append(
            {
                **alert,
                "consecutive_observations": int(prior.get("consecutive_observations", 0)) + 1,
                "first_seen_at": prior.get("first_seen_at", timestamp),
                "last_seen_at": timestamp,
            }
        )
    current_codes = {alert["code"] for alert in alerts}
    resolved = [
        {"code": code, "resolved_at": timestamp}
        for code in sorted(previous_by_code)
        if code not in current_codes
    ]
    return {
        "active_alerts": active,
        "observed_at": timestamp,
        "resolved_alerts": resolved,
        "schema_version": "operational-alert-state-v1",
    }
