from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "evaluate-hci-participant-study.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evaluate_hci_participant_study", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task(status: str = "independent_success") -> dict:
    return {
        "status": status,
        "duration_seconds": 30,
        "recoverable_errors": 0,
        "unrecoverable_errors": 0,
        "help_requests": 0,
        "backtracks": 0,
    }


def _session(code: str, *, sus: list[int] | None = None) -> dict:
    return {
        "participant_code": code,
        "valid": True,
        "exclusion_reason": None,
        "eligibility": {
            "adult": True,
            "target_reader": True,
            "experience_band": "regular",
            "contributor": False,
            "saw_task_script": False,
        },
        "consent_confirmed": True,
        "session_date": "2026-08-24",
        "device_class": "desktop",
        "viewport_class": "desktop",
        "tasks": {str(number): _task() for number in range(1, 11)},
        "first_scene_seconds": 120,
        "normal_action_agency_correct": True,
        "continue_scope_correct": True,
        "recovery_attempted": True,
        "recovery_succeeded": True,
        "confidence": 4,
        "sus_responses": sus or [5, 1, 5, 1, 5, 1, 5, 1, 5, 1],
        "observation_codes": [],
        "protocol_deviations": [],
    }


def _study(module, sessions: list[dict], *, mode: str = "formal") -> dict:
    return {
        "schema_version": module.SCHEMA_VERSION,
        "study_id": "witscraft-hci-20260824-r1",
        "study_mode": mode,
        "round_number": 1,
        "tested_revision": "a" * 40,
        "candidate": {
            "manifest_schema": 1,
            "migration_heads": ["0022"],
            "frontend_build_id": "test-build",
        },
        "protocol_sha256": module._protocol_sha256(),
        "prior_round_participant_codes": [],
        "sessions": sessions,
        "issues": [],
    }


def test_complete_five_player_gate_passes_and_scores_sus() -> None:
    module = _load_module()
    sessions = [_session(f"P-{number:08X}") for number in range(1, 6)]

    report = module.evaluate_study(_study(module, sessions))

    assert report["status"] == "passed"
    assert report["metrics"]["critical_task_completion_rate"] == 1.0
    assert report["metrics"]["first_scene_median_seconds"] == 120
    assert report["metrics"]["sus_mean"] == 100.0
    assert all(report["criteria"].values())


def test_incomplete_or_rehearsal_data_cannot_claim_participant_pass() -> None:
    module = _load_module()
    pending = module.evaluate_study(_study(module, [_session("P-00000001")]))
    rehearsal = module.evaluate_study(
        _study(module, [_session(f"P-{number:08X}") for number in range(1, 6)], mode="rehearsal")
    )

    assert pending["status"] == "pending"
    assert rehearsal["status"] == "rehearsal"


def test_failed_authority_sus_recovery_and_severe_issue_fail_gate() -> None:
    module = _load_module()
    sessions = [_session(f"P-{number:08X}") for number in range(1, 6)]
    sessions[0]["normal_action_agency_correct"] = False
    sessions[1]["continue_scope_correct"] = False
    sessions[2]["recovery_succeeded"] = False
    sessions[3]["sus_responses"] = [3] * 10
    study = _study(module, sessions)
    study["issues"] = [
        {
            "issue_id": "HCI-R1-001",
            "severity": 1,
            "principle": "control",
            "title": "Players cannot distinguish normal action authority",
            "status": "open",
            "fixed_revision": None,
        }
    ]

    report = module.evaluate_study(study)

    assert report["status"] == "failed"
    assert report["criteria"]["normal_action_agency"] is False
    assert report["criteria"]["continue_scope"] is False
    assert report["criteria"]["failure_recovery"] is False
    assert report["criteria"]["no_open_severity_0_or_1"] is False


def test_unknown_or_sensitive_fields_are_rejected_without_echoing_values() -> None:
    module = _load_module()
    study = _study(module, [_session("P-00000001")])
    study["sessions"][0]["email"] = "person@example.com"

    with pytest.raises(module.StudyValidationError, match="prohibited data field") as error:
        module.validate_study(study)

    assert "person@example.com" not in str(error.value)


def test_missing_sus_is_not_imputed_and_retest_requires_three_new_players() -> None:
    module = _load_module()
    sessions = [_session(f"P-{number:08X}") for number in range(1, 6)]
    sessions[0]["sus_responses"] = None
    report = module.evaluate_study(_study(module, sessions))
    assert report["status"] == "failed"
    assert report["metrics"]["sus_missing"] == 1
    assert report["criteria"]["sus"] is False

    retest = _study(module, sessions)
    retest["study_id"] = "witscraft-hci-20260824-r2"
    retest["round_number"] = 2
    retest["prior_round_participant_codes"] = [session["participant_code"] for session in sessions]
    retest_report = module.evaluate_study(retest)
    assert retest_report["criteria"]["retest_new_participants"] is False


def test_retest_rejects_an_incomplete_prior_participant_set() -> None:
    module = _load_module()
    sessions = [_session(f"P-{number:08X}") for number in range(1, 6)]
    retest = _study(module, sessions)
    retest["study_id"] = "witscraft-hci-20260824-r2"
    retest["round_number"] = 2
    retest["prior_round_participant_codes"] = ["P-00000001"]

    with pytest.raises(module.StudyValidationError, match="at least five prior-round"):
        module.validate_study(retest)
