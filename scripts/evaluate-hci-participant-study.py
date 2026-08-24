#!/usr/bin/env python3
"""Create and evaluate privacy-minimized target-player HCI study records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import statistics
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
PROTOCOL = ROOT / "docs" / "hci-participant-study.md"
SCHEMA_VERSION = "hci-participant-study-v1"
TASK_IDS = tuple(str(number) for number in range(1, 11))
CRITICAL_TASK_IDS = tuple(str(number) for number in range(2, 8))
TASK_STATUSES = {"independent_success", "helped", "failed", "not_attempted"}
EXPERIENCE_BANDS = {"some", "regular", "extensive"}
DEVICE_CLASSES = {"desktop", "tablet", "mobile"}
VIEWPORT_CLASSES = {"desktop", "tablet", "390x844_mobile"}
EXCLUSION_REASONS = {
    "eligibility_failed",
    "consent_withdrawn",
    "technical_failure_before_task_2",
    "duplicate_participation",
    "protocol_compromised",
}
OBSERVATION_CODES = {
    "product_purpose_unclear",
    "creation_controls_unclear",
    "agency_normal_turn_unclear",
    "continue_scope_unclear",
    "choice_effect_unclear",
    "recovery_action_unclear",
    "branch_canon_unclear",
    "chapter_minimum_unclear",
    "quota_scope_unclear",
    "navigation_confusion",
    "accessibility_barrier",
}
PRINCIPLES = {
    "visibility",
    "mental_model",
    "control",
    "error_prevention",
    "accessibility",
    "ai_trust",
    "consistency",
    "recovery",
    "recognition",
    "minimalism",
    "flexibility",
    "onboarding",
}
PROTOCOL_DEVIATIONS = {
    "facilitator_assistance",
    "environment_interruption",
    "provider_failure_not_staged",
    "questionnaire_incomplete",
    "session_stopped_by_participant",
}
FORBIDDEN_KEY_PARTS = {
    "name",
    "email",
    "contact",
    "address",
    "ip",
    "cookie",
    "credential",
    "password",
    "token",
    "prompt",
    "prose",
    "story_text",
    "transcript",
    "recording",
}
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9])"),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b(?:bearer|api[_ -]?key|password|session[_ -]?token)\b", re.IGNORECASE),
)


class StudyValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StudyValidationError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    _require(not missing, f"{path} is missing fields: {', '.join(sorted(missing))}")
    _require(not extra, f"{path} contains prohibited fields: {', '.join(sorted(extra))}")


def _scan_keys(value: Any, path: str = "study") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            key_parts = set(normalized.split("_"))
            if key != "participant_code" and (
                normalized in FORBIDDEN_KEY_PARTS or key_parts & FORBIDDEN_KEY_PARTS
            ):
                raise StudyValidationError(f"{path}.{key} is a prohibited data field")
            _scan_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_keys(child, f"{path}[{index}]")


def _safe_short_text(value: Any, path: str, maximum: int) -> str:
    _require(isinstance(value, str), f"{path} must be text")
    _require(1 <= len(value) <= maximum, f"{path} must contain 1-{maximum} characters")
    _require("\n" not in value and "\r" not in value, f"{path} must be one line")
    for pattern in SENSITIVE_VALUE_PATTERNS:
        _require(not pattern.search(value), f"{path} contains prohibited sensitive content")
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    _require(type(value) is int, f"{path} must be an integer")
    _require(minimum <= value <= maximum, f"{path} is outside {minimum}-{maximum}")
    return value


def _boolean(value: Any, path: str) -> bool:
    _require(type(value) is bool, f"{path} must be true or false")
    return value


def _nullable_boolean(value: Any, path: str) -> bool | None:
    _require(value is None or type(value) is bool, f"{path} must be true, false, or null")
    return value


def _protocol_sha256() -> str:
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_task(task: Any, path: str) -> dict[str, Any]:
    _require(isinstance(task, dict), f"{path} must be an object")
    _exact_keys(
        task,
        {
            "status",
            "duration_seconds",
            "recoverable_errors",
            "unrecoverable_errors",
            "help_requests",
            "backtracks",
        },
        path,
    )
    _require(task["status"] in TASK_STATUSES, f"{path}.status is invalid")
    for field in (
        "duration_seconds",
        "recoverable_errors",
        "unrecoverable_errors",
        "help_requests",
        "backtracks",
    ):
        maximum = 7200 if field == "duration_seconds" else 100
        _integer(task[field], f"{path}.{field}", 0, maximum)
    return task


def _validate_session(session: Any, index: int) -> dict[str, Any]:
    path = f"study.sessions[{index}]"
    _require(isinstance(session, dict), f"{path} must be an object")
    _exact_keys(
        session,
        {
            "participant_code",
            "valid",
            "exclusion_reason",
            "eligibility",
            "consent_confirmed",
            "session_date",
            "device_class",
            "viewport_class",
            "tasks",
            "first_scene_seconds",
            "normal_action_agency_correct",
            "continue_scope_correct",
            "recovery_attempted",
            "recovery_succeeded",
            "confidence",
            "sus_responses",
            "observation_codes",
            "protocol_deviations",
        },
        path,
    )
    _require(
        isinstance(session["participant_code"], str)
        and re.fullmatch(r"P-[A-F0-9]{8}", session["participant_code"]) is not None,
        f"{path}.participant_code must be a generated anonymous code",
    )
    valid = _boolean(session["valid"], f"{path}.valid")
    if valid:
        _require(session["exclusion_reason"] is None, f"{path} valid session cannot be excluded")
    else:
        _require(
            session["exclusion_reason"] in EXCLUSION_REASONS,
            f"{path}.exclusion_reason is required for an invalid session",
        )

    eligibility = session["eligibility"]
    _require(isinstance(eligibility, dict), f"{path}.eligibility must be an object")
    _exact_keys(
        eligibility,
        {"adult", "target_reader", "experience_band", "contributor", "saw_task_script"},
        f"{path}.eligibility",
    )
    for field in ("adult", "target_reader", "contributor", "saw_task_script"):
        _boolean(eligibility[field], f"{path}.eligibility.{field}")
    _require(
        eligibility["experience_band"] in EXPERIENCE_BANDS,
        f"{path}.eligibility.experience_band is invalid",
    )
    _boolean(session["consent_confirmed"], f"{path}.consent_confirmed")
    if valid:
        _require(
            eligibility["adult"]
            and eligibility["target_reader"]
            and not eligibility["contributor"]
            and not eligibility["saw_task_script"]
            and session["consent_confirmed"],
            f"{path} does not meet eligibility and consent requirements",
        )

    _require(
        isinstance(session["session_date"], str)
        and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", session["session_date"]) is not None,
        f"{path}.session_date must be an ISO date without a timestamp",
    )
    _require(session["device_class"] in DEVICE_CLASSES, f"{path}.device_class is invalid")
    _require(
        session["viewport_class"] in VIEWPORT_CLASSES,
        f"{path}.viewport_class is invalid",
    )
    tasks = session["tasks"]
    _require(isinstance(tasks, dict), f"{path}.tasks must be an object")
    _exact_keys(tasks, set(TASK_IDS), f"{path}.tasks")
    for task_id in TASK_IDS:
        _validate_task(tasks[task_id], f"{path}.tasks.{task_id}")

    first_scene = session["first_scene_seconds"]
    _require(first_scene is None or type(first_scene) is int, f"{path}.first_scene_seconds is invalid")
    if first_scene is not None:
        _integer(first_scene, f"{path}.first_scene_seconds", 1, 7200)
    _nullable_boolean(
        session["normal_action_agency_correct"],
        f"{path}.normal_action_agency_correct",
    )
    _nullable_boolean(session["continue_scope_correct"], f"{path}.continue_scope_correct")
    recovery_attempted = _boolean(session["recovery_attempted"], f"{path}.recovery_attempted")
    recovery_succeeded = _nullable_boolean(
        session["recovery_succeeded"], f"{path}.recovery_succeeded"
    )
    _require(
        recovery_attempted or recovery_succeeded is None,
        f"{path}.recovery_succeeded must be null when recovery was not attempted",
    )
    confidence = session["confidence"]
    _require(confidence is None or type(confidence) is int, f"{path}.confidence is invalid")
    if confidence is not None:
        _integer(confidence, f"{path}.confidence", 1, 5)
    sus = session["sus_responses"]
    _require(sus is None or isinstance(sus, list), f"{path}.sus_responses must be a list or null")
    if sus is not None:
        _require(len(sus) == 10, f"{path}.sus_responses must contain all 10 answers")
        for answer_index, answer in enumerate(sus):
            _integer(answer, f"{path}.sus_responses[{answer_index}]", 1, 5)
    observations = session["observation_codes"]
    _require(isinstance(observations, list), f"{path}.observation_codes must be a list")
    _require(len(observations) == len(set(observations)), f"{path}.observation_codes has duplicates")
    _require(set(observations) <= OBSERVATION_CODES, f"{path}.observation_codes is invalid")
    deviations = session["protocol_deviations"]
    _require(isinstance(deviations, list), f"{path}.protocol_deviations must be a list")
    _require(len(deviations) == len(set(deviations)), f"{path}.protocol_deviations has duplicates")
    _require(set(deviations) <= PROTOCOL_DEVIATIONS, f"{path}.protocol_deviations is invalid")
    return session


def _validate_issue(issue: Any, index: int) -> dict[str, Any]:
    path = f"study.issues[{index}]"
    _require(isinstance(issue, dict), f"{path} must be an object")
    _exact_keys(
        issue,
        {"issue_id", "severity", "principle", "title", "status", "fixed_revision"},
        path,
    )
    _require(
        isinstance(issue["issue_id"], str)
        and re.fullmatch(r"HCI-R\d+-\d{3}", issue["issue_id"]) is not None,
        f"{path}.issue_id is invalid",
    )
    _integer(issue["severity"], f"{path}.severity", 0, 3)
    _require(issue["principle"] in PRINCIPLES, f"{path}.principle is invalid")
    _safe_short_text(issue["title"], f"{path}.title", 160)
    _require(issue["status"] in {"open", "resolved"}, f"{path}.status is invalid")
    fixed_revision = issue["fixed_revision"]
    _require(
        fixed_revision is None
        or (isinstance(fixed_revision, str) and re.fullmatch(r"[0-9a-f]{40}", fixed_revision)),
        f"{path}.fixed_revision is invalid",
    )
    _require(
        issue["status"] == "open" or fixed_revision is not None,
        f"{path}.fixed_revision is required when resolved",
    )
    return issue


def validate_study(payload: Any) -> dict[str, Any]:
    _require(isinstance(payload, dict), "study must be an object")
    _scan_keys(payload)
    _exact_keys(
        payload,
        {
            "schema_version",
            "study_id",
            "study_mode",
            "round_number",
            "tested_revision",
            "candidate",
            "protocol_sha256",
            "prior_round_participant_codes",
            "sessions",
            "issues",
        },
        "study",
    )
    _require(payload["schema_version"] == SCHEMA_VERSION, "study.schema_version is unsupported")
    _require(
        isinstance(payload["study_id"], str)
        and re.fullmatch(r"witscraft-hci-20\d{6}-r\d+", payload["study_id"]) is not None,
        "study.study_id is invalid",
    )
    _require(payload["study_mode"] in {"rehearsal", "formal"}, "study.study_mode is invalid")
    round_number = _integer(payload["round_number"], "study.round_number", 1, 20)
    _require(
        isinstance(payload["tested_revision"], str)
        and re.fullmatch(r"[0-9a-f]{40}", payload["tested_revision"]) is not None,
        "study.tested_revision must be a full Git revision",
    )
    candidate = payload["candidate"]
    _require(isinstance(candidate, dict), "study.candidate must be an object")
    _exact_keys(
        candidate,
        {"manifest_schema", "migration_heads", "frontend_build_id"},
        "study.candidate",
    )
    _integer(candidate["manifest_schema"], "study.candidate.manifest_schema", 1, 100)
    _require(
        isinstance(candidate["migration_heads"], list)
        and candidate["migration_heads"]
        and all(isinstance(item, str) and re.fullmatch(r"\d{4}", item) for item in candidate["migration_heads"]),
        "study.candidate.migration_heads is invalid",
    )
    _safe_short_text(candidate["frontend_build_id"], "study.candidate.frontend_build_id", 128)
    _require(
        payload["protocol_sha256"] == _protocol_sha256(),
        "study.protocol_sha256 does not match the current approved protocol",
    )
    prior_codes = payload["prior_round_participant_codes"]
    _require(isinstance(prior_codes, list), "study.prior_round_participant_codes must be a list")
    _require(len(prior_codes) == len(set(prior_codes)), "prior participant codes contain duplicates")
    _require(
        all(isinstance(code, str) and re.fullmatch(r"P-[A-F0-9]{8}", code) for code in prior_codes),
        "prior participant codes are invalid",
    )
    _require(round_number > 1 or not prior_codes, "round one cannot contain prior participant codes")
    _require(
        round_number == 1 or len(prior_codes) >= 5,
        "a retest must bind at least five prior-round participant codes",
    )

    sessions = payload["sessions"]
    _require(isinstance(sessions, list), "study.sessions must be a list")
    for index, session in enumerate(sessions):
        _validate_session(session, index)
    participant_codes = [session["participant_code"] for session in sessions]
    _require(len(participant_codes) == len(set(participant_codes)), "participant codes must be unique")
    issues = payload["issues"]
    _require(isinstance(issues, list), "study.issues must be a list")
    for index, issue in enumerate(issues):
        _validate_issue(issue, index)
    issue_ids = [issue["issue_id"] for issue in issues]
    _require(len(issue_ids) == len(set(issue_ids)), "issue IDs must be unique")
    return payload


def sus_score(responses: list[int]) -> float:
    contribution = 0
    for index, response in enumerate(responses):
        contribution += response - 1 if index % 2 == 0 else 5 - response
    return contribution * 2.5


def evaluate_study(payload: dict[str, Any]) -> dict[str, Any]:
    validate_study(payload)
    valid_sessions = [session for session in payload["sessions"] if session["valid"]]
    critical_attempts = len(valid_sessions) * len(CRITICAL_TASK_IDS)
    critical_successes = sum(
        session["tasks"][task_id]["status"] == "independent_success"
        for session in valid_sessions
        for task_id in CRITICAL_TASK_IDS
    )
    critical_completion = critical_successes / critical_attempts if critical_attempts else 0.0
    first_scene_values = [
        session["first_scene_seconds"]
        for session in valid_sessions
        if session["first_scene_seconds"] is not None
    ]
    confidence_values = [
        session["confidence"] for session in valid_sessions if session["confidence"] is not None
    ]
    sus_scores = {
        session["participant_code"]: sus_score(session["sus_responses"])
        for session in valid_sessions
        if session["sus_responses"] is not None
    }
    recovery_attempts = sum(session["recovery_attempted"] for session in valid_sessions)
    recovery_successes = sum(
        session["recovery_succeeded"] is True
        for session in valid_sessions
        if session["recovery_attempted"]
    )
    recovery_rate = recovery_successes / recovery_attempts if recovery_attempts else 0.0
    normal_agency_misunderstandings = sum(
        session["normal_action_agency_correct"] is not True for session in valid_sessions
    )
    continue_scope_correct = sum(
        session["continue_scope_correct"] is True for session in valid_sessions
    )
    open_severe_issues = [
        issue["issue_id"]
        for issue in payload["issues"]
        if issue["status"] == "open" and issue["severity"] in {0, 1}
    ]
    prior_codes = set(payload["prior_round_participant_codes"])
    new_participant_count = sum(
        session["valid"] and session["participant_code"] not in prior_codes
        for session in payload["sessions"]
    )
    valid_count = len(valid_sessions)
    sus_values = list(sus_scores.values())
    first_scene_median = statistics.median(first_scene_values) if first_scene_values else None
    confidence_median = statistics.median(confidence_values) if confidence_values else None
    sus_mean = statistics.fmean(sus_values) if sus_values else None
    criteria = {
        "minimum_valid_sessions": valid_count >= 5,
        "critical_task_completion": critical_completion >= 0.9,
        "first_scene_time": len(first_scene_values) == valid_count
        and first_scene_median is not None
        and first_scene_median < 180,
        "normal_action_agency": valid_count >= 5 and normal_agency_misunderstandings == 0,
        "continue_scope": valid_count >= 5 and continue_scope_correct == valid_count,
        "failure_recovery": recovery_attempts == valid_count and recovery_rate >= 0.9,
        "post_task_confidence": len(confidence_values) == valid_count
        and confidence_median is not None
        and confidence_median >= 4,
        "sus": len(sus_scores) == valid_count and sus_mean is not None and sus_mean >= 80,
        "no_open_severity_0_or_1": not open_severe_issues,
        "retest_new_participants": payload["round_number"] == 1 or new_participant_count >= 3,
    }
    if payload["study_mode"] == "rehearsal":
        status = "rehearsal"
    elif valid_count < 5:
        status = "pending"
    else:
        status = "passed" if all(criteria.values()) else "failed"
    per_task = {}
    for task_id in TASK_IDS:
        independent = sum(
            session["tasks"][task_id]["status"] == "independent_success"
            for session in valid_sessions
        )
        errors = sum(
            session["tasks"][task_id]["recoverable_errors"]
            + session["tasks"][task_id]["unrecoverable_errors"]
            for session in valid_sessions
        )
        per_task[task_id] = {
            "independent_successes": independent,
            "attempts": valid_count,
            "error_count": errors,
            "error_rate_per_attempt": round(errors / valid_count, 4) if valid_count else 0.0,
        }
    return {
        "schema_version": "hci-participant-report-v1",
        "study_id": payload["study_id"],
        "study_mode": payload["study_mode"],
        "round_number": payload["round_number"],
        "tested_revision": payload["tested_revision"],
        "candidate": payload["candidate"],
        "protocol_sha256": payload["protocol_sha256"],
        "input_sha256": _canonical_sha256(payload),
        "status": status,
        "counts": {
            "valid_sessions": valid_count,
            "excluded_sessions": len(payload["sessions"]) - valid_count,
            "new_valid_participants": new_participant_count,
        },
        "metrics": {
            "critical_task_successes": critical_successes,
            "critical_task_attempts": critical_attempts,
            "critical_task_completion_rate": round(critical_completion, 4),
            "first_scene_median_seconds": first_scene_median,
            "normal_action_agency_misunderstandings": normal_agency_misunderstandings,
            "continue_scope_correct": continue_scope_correct,
            "recovery_successes": recovery_successes,
            "recovery_attempts": recovery_attempts,
            "recovery_rate": round(recovery_rate, 4),
            "confidence_median": confidence_median,
            "sus_mean": round(sus_mean, 2) if sus_mean is not None else None,
            "sus_median": statistics.median(sus_values) if sus_values else None,
            "sus_range": [min(sus_values), max(sus_values)] if sus_values else None,
            "sus_missing": valid_count - len(sus_scores),
        },
        "per_task": per_task,
        "participant_summaries": [
            {
                "participant_code": session["participant_code"],
                "session_date": session["session_date"],
                "device_class": session["device_class"],
                "viewport_class": session["viewport_class"],
                "valid": session["valid"],
                "exclusion_reason": session["exclusion_reason"],
                "confidence": session["confidence"] if session["valid"] else None,
                "sus_score": sus_scores.get(session["participant_code"]),
                "observation_codes": session["observation_codes"],
                "protocol_deviations": session["protocol_deviations"],
            }
            for session in payload["sessions"]
        ],
        "issues": payload["issues"],
        "open_severity_0_or_1": open_severe_issues,
        "criteria": criteria,
    }


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _runtime_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    _require(resolved.is_relative_to(RUNTIME.resolve()), "raw study input must remain under .runtime")
    return resolved


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _write_sanitized_report(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise StudyValidationError("sanitized report output already exists")
    private_runtime_output = path.is_relative_to(RUNTIME.resolve())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private_runtime_output else 0o755)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600 if private_runtime_output else 0o644)
    temporary.replace(path)


def _initial_payload(manifest_path: Path, study_id: str, mode: str, round_number: int) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    revision = _git_revision()
    _require(manifest.get("application_revision") == revision, "candidate revision is not current HEAD")
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": study_id,
        "study_mode": mode,
        "round_number": round_number,
        "tested_revision": revision,
        "candidate": {
            "manifest_schema": manifest["manifest_schema"],
            "migration_heads": manifest["migration_heads"],
            "frontend_build_id": manifest["frontend"]["build_id"],
        },
        "protocol_sha256": _protocol_sha256(),
        "prior_round_participant_codes": [],
        "sessions": [],
        "issues": [],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init", help="create a private empty study record")
    initialize.add_argument("--output", type=Path, required=True)
    initialize.add_argument("--manifest", type=Path, required=True)
    initialize.add_argument("--study-id", required=True)
    initialize.add_argument("--mode", choices=("rehearsal", "formal"), required=True)
    initialize.add_argument("--round", type=int, default=1)
    evaluate = subparsers.add_parser("evaluate", help="validate and aggregate a private study record")
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--require-pass", action="store_true")
    subparsers.add_parser("new-code", help="generate a random anonymous participant code")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        if args.command == "new-code":
            print(f"P-{secrets.token_hex(4).upper()}")
            return
        if args.command == "init":
            output = _runtime_path(args.output)
            _require(not output.exists(), "private study output already exists")
            payload = _initial_payload(
                args.manifest.expanduser().resolve(),
                args.study_id,
                args.mode,
                args.round,
            )
            validate_study(payload)
            _write_private_json(output, payload)
            print(f"Private HCI study initialized: {output}")
            return
        input_path = _runtime_path(args.input)
        _require(input_path.is_file(), "private study input is missing")
        _require(
            input_path.stat().st_mode & 0o777 == 0o600,
            "private study input must have mode 0600",
        )
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        report = evaluate_study(payload)
        if args.output:
            output = args.output.expanduser().resolve()
            _write_sanitized_report(output, report)
            print(f"Sanitized HCI report written: {output}")
        print(f"HCI participant gate: {report['status']}")
        print(f"Valid sessions: {report['counts']['valid_sessions']}")
        if args.require_pass and report["status"] != "passed":
            raise StudyValidationError("participant gate has not passed")
    except (KeyError, json.JSONDecodeError, OSError, StudyValidationError) as exc:
        raise SystemExit(f"HCI participant study rejected: {exc}") from None


if __name__ == "__main__":
    main()
