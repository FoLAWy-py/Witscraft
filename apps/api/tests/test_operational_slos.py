import json
from datetime import datetime, timedelta, timezone

from app.operational_logging import ACCESS_METRIC_MARKER
from app.services.operational_slos import (
    SLOPolicy,
    evaluate_slo_snapshot,
    http_snapshot,
    merge_alert_state,
    parse_access_metric_lines,
    percentile,
)


def _line(observed_at: datetime, **updates) -> str:
    payload = {
        "duration_ms": 25.0,
        "event": "http_request",
        "method": "GET",
        "observed_at": observed_at.isoformat(),
        "request_id": "ignored-by-aggregation",
        "route": "/api/workspace",
        "status_code": 200,
    }
    payload.update(updates)
    return f"{ACCESS_METRIC_MARKER}{json.dumps(payload)}"


def test_access_parser_and_http_snapshot_are_bounded_to_metadata_and_window() -> None:
    now = datetime.now(timezone.utc)
    events = parse_access_metric_lines(
        [
            _line(now - timedelta(minutes=2)),
            _line(now - timedelta(minutes=1), route="/api/chat/stream", duration_ms=90_000),
            _line(now, route="/api/workspace", status_code=503, duration_ms=3000),
            _line(now, route="/health/ready", duration_ms=5),
            _line(now, route="/api/admin/overview", duration_ms=6),
            _line(now, method="OPTIONS", duration_ms=7),
            _line(now - timedelta(hours=2)),
            "not a metric",
            f"{ACCESS_METRIC_MARKER}{{broken",
        ],
        since=now - timedelta(minutes=30),
    )
    snapshot = http_snapshot(events)

    assert snapshot["requests"] == 3
    assert snapshot["server_errors"] == 1
    assert snapshot["server_error_rate"] == 0.333333
    assert snapshot["non_stream_latency_samples"] == 2
    assert snapshot["non_stream_p95_ms"] == 3000
    assert snapshot["by_route"]["/api/chat/stream"] == {
        "requests": 1,
        "server_errors": 0,
    }
    assert percentile([10, 20, 30, 40], 0.95) == 40


def test_slo_evaluation_alerts_failures_and_marks_low_samples_without_alerting() -> None:
    policy = SLOPolicy(minimum_http_samples=2, minimum_model_samples=2)
    snapshot = {
        "backup": {"newest_age_seconds": policy.maximum_backup_age_seconds + 1},
        "database": {"available": False},
        "embedding": {
            "dead": 1,
            "oldest_queue_age_seconds": policy.maximum_embedding_queue_age_seconds + 1,
            "stale_running": 1,
        },
        "generation": {
            "oldest_processing_age_seconds": 700,
            "stuck_processing": 1,
        },
        "http": {
            "non_stream_latency_samples": 2,
            "non_stream_p95_ms": 3000,
            "requests": 2,
            "server_error_rate": 0.5,
        },
        "model": {
            "calls": 2,
            "latency_samples": 2,
            "p95_latency_ms": 70_000,
            "p95_ttft_ms": 20_000,
            "success_rate": 0.5,
            "ttft_samples": 2,
        },
        "readiness": {"ready": False},
    }
    result = evaluate_slo_snapshot(snapshot, policy)

    assert not result["passed"]
    assert {alert["code"] for alert in result["alerts"]} == {
        "backup_missing_or_old",
        "embedding_dead_letters",
        "embedding_queue_old",
        "embedding_stale_leases",
        "generation_processing_stuck",
        "http_5xx_rate_high",
        "http_p95_high",
        "metrics_database_failed",
        "model_p95_high",
        "model_success_rate_low",
        "model_ttft_p95_high",
        "readiness_failed",
    }
    low_sample = evaluate_slo_snapshot(
        {
            "backup": {"newest_age_seconds": 1},
            "database": {"available": True},
            "embedding": {},
            "generation": {},
            "http": {"requests": 0, "non_stream_latency_samples": 0},
            "model": {"calls": 0},
            "readiness": {"ready": True},
        },
        policy,
    )
    assert low_sample["passed"]
    assert low_sample["alerts"] == []
    assert low_sample["insufficient_samples"] == [
        "http_availability",
        "http_latency",
        "model_success",
    ]


def test_alert_state_preserves_first_seen_and_reports_resolution() -> None:
    first = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
    alert = {
        "code": "readiness_failed",
        "severity": "critical",
        "threshold": "ready",
        "value": "not_ready",
    }
    initial = merge_alert_state(None, [alert], observed_at=first)
    repeated = merge_alert_state(initial, [alert], observed_at=first + timedelta(minutes=5))
    resolved = merge_alert_state(repeated, [], observed_at=first + timedelta(minutes=10))

    assert repeated["active_alerts"][0]["first_seen_at"] == first.isoformat()
    assert repeated["active_alerts"][0]["consecutive_observations"] == 2
    assert resolved["active_alerts"] == []
    assert resolved["resolved_alerts"] == [
        {"code": "readiness_failed", "resolved_at": (first + timedelta(minutes=10)).isoformat()}
    ]
