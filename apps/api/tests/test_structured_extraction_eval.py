import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.evals.structured_extraction import (
    evaluate_recorded_responses,
    load_json,
    validate_route_approval,
)
from app.llm.model_registry import PURPOSE_DEFAULTS, get_model


EVAL_ROOT = Path(__file__).parents[1] / "evals" / "structured_extraction" / "v1"
REPOSITORY_ROOT = Path(__file__).parents[3]


def _fixtures() -> tuple[dict, dict, dict[str, float]]:
    cases = load_json(EVAL_ROOT / "cases.json")
    responses = load_json(EVAL_ROOT / "reference_responses.json")
    thresholds = load_json(EVAL_ROOT / "thresholds.json")["thresholds"]
    return cases, responses, thresholds


def test_reference_structured_extraction_contract_passes() -> None:
    cases, responses, thresholds = _fixtures()

    report = evaluate_recorded_responses(cases, responses, thresholds)

    assert report.passed is True
    assert report.metrics.case_count == 8
    assert report.metrics.parse_success_rate == 1.0
    assert report.metrics.scalar_accuracy == 1.0
    assert report.metrics.collection_f1 == 1.0
    assert report.metrics.relationship_f1 == 1.0
    assert report.metrics.critical_pass_rate == 1.0
    assert report.metrics.hallucination_rate == 0.0


def test_invalid_candidate_response_fails_quality_thresholds() -> None:
    cases, responses, thresholds = _fixtures()
    candidate = copy.deepcopy(responses)
    candidate["responses"]["explicit-arrival-and-stable-fact"] = "not json"

    report = evaluate_recorded_responses(cases, candidate, thresholds)

    assert report.passed is False
    assert report.metrics.parse_success_rate < thresholds["min_parse_success_rate"]
    assert any("parse_success_rate" in failure for failure in report.failures)


def test_response_bundle_must_cover_exact_case_set() -> None:
    cases, responses, thresholds = _fixtures()
    responses = copy.deepcopy(responses)
    responses["responses"].pop("quiet-turn-preserves-state")

    with pytest.raises(ValueError, match="coverage mismatch"):
        evaluate_recorded_responses(cases, responses, thresholds)


def test_synthetic_contract_cannot_approve_provider_route() -> None:
    cases, responses, thresholds = _fixtures()

    with pytest.raises(ValueError, match="provider_capture"):
        evaluate_recorded_responses(
            cases,
            responses,
            thresholds,
            require_provider_evidence=True,
        )


def test_response_bundle_is_bound_to_case_content_hash() -> None:
    cases, responses, thresholds = _fixtures()
    changed_cases = copy.deepcopy(cases)
    changed_cases["cases"][0]["assistant_turn"] += "变化"

    with pytest.raises(ValueError, match="case_set_sha256"):
        evaluate_recorded_responses(changed_cases, responses, thresholds)


def test_case_set_is_bound_to_exact_application_prompt() -> None:
    cases, responses, thresholds = _fixtures()
    changed_cases = copy.deepcopy(cases)
    changed_cases["prompt_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="prompt_sha256"):
        evaluate_recorded_responses(changed_cases, responses, thresholds)


def test_current_structured_default_matches_route_approval() -> None:
    cases, _, thresholds = _fixtures()
    approval = load_json(EVAL_ROOT / "route_approval.json")
    model = get_model(PURPOSE_DEFAULTS["state_update"])
    assert model is not None

    report = validate_route_approval(
        cases,
        thresholds,
        approval,
        evaluation_root=EVAL_ROOT,
        current_provider=model.provider,
        current_model=model.model,
    )

    assert report is not None
    assert report.passed is True
    assert report.evidence_kind == "provider_capture"
    assert report.metrics.scalar_accuracy == 1.0
    assert report.metrics.collection_f1 == 1.0
    assert report.metrics.relationship_f1 == 1.0
    assert report.metrics.hallucination_rate == 0.0


def test_default_cli_reports_real_provider_score_as_primary_result() -> None:
    completed = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts/evaluate-structured-extraction.py")],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["evidence_kind"] == "provider_capture"
    assert payload["provider"] == "deepinfra"
    assert payload["model"] == "Qwen/Qwen3-Max"
    assert payload["route_approval"]["score_source"] == "provider_capture"
    assert payload["metrics"] == payload["route_approval"]["provider_evidence_metrics"]


def test_legacy_exception_cannot_approve_a_different_model() -> None:
    cases, _, thresholds = _fixtures()
    approval = load_json(EVAL_ROOT / "route_approval.json")
    changed = copy.deepcopy(approval)
    changed["state_update_route"].update(
        {
            "model": "zai-org/GLM-5.2",
            "evidence_kind": "legacy_pre_evaluation_default",
        }
    )
    changed["state_update_route"].pop("response_bundle", None)

    with pytest.raises(ValueError, match="legacy exception"):
        validate_route_approval(
            cases,
            thresholds,
            changed,
            evaluation_root=EVAL_ROOT,
            current_provider="deepinfra",
            current_model="zai-org/GLM-5.2",
        )


def test_provider_approval_bundle_cannot_escape_evaluation_root() -> None:
    cases, _, thresholds = _fixtures()
    approval = load_json(EVAL_ROOT / "route_approval.json")
    changed = copy.deepcopy(approval)
    changed["state_update_route"].update(
        {
            "evidence_kind": "provider_capture",
            "response_bundle": "../../outside.json",
        }
    )

    with pytest.raises(ValueError, match="inside the evaluation root"):
        validate_route_approval(
            cases,
            thresholds,
            changed,
            evaluation_root=EVAL_ROOT,
            current_provider="deepinfra",
            current_model="Qwen/Qwen3-Max",
        )


def test_route_approval_is_bound_to_prompt_version() -> None:
    cases, _, thresholds = _fixtures()
    approval = load_json(EVAL_ROOT / "route_approval.json")
    changed = copy.deepcopy(approval)
    changed["prompt_version"] = "state-extraction-stale"

    with pytest.raises(ValueError, match="prompt_version"):
        validate_route_approval(
            cases,
            thresholds,
            changed,
            evaluation_root=EVAL_ROOT,
            current_provider="deepinfra",
            current_model="Qwen/Qwen3-Max",
        )
