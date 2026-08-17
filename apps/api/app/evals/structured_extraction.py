from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.schemas.chat import StoryState
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.state_extractor import (
    STATE_EXTRACTION_PROMPT_VERSION,
    STATE_EXTRACTION_SYSTEM_PROMPT,
    ExtractionResult,
    extract_story_updates_with_llm,
)


LEGACY_STRUCTURED_ROUTE = ("deepinfra", "Qwen/Qwen3-Max")


@dataclass(frozen=True)
class EvaluationMetrics:
    case_count: int
    parse_success_rate: float
    scalar_accuracy: float
    collection_f1: float
    relationship_f1: float
    critical_pass_rate: float
    hallucination_rate: float


@dataclass(frozen=True)
class EvaluationReport:
    evaluation_version: str
    prompt_version: str
    evidence_kind: str
    provider: str
    model: str
    metrics: EvaluationMetrics
    thresholds: dict[str, float]
    passed: bool
    failures: list[str]
    cases: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = asdict(self.metrics)
        return payload


class _RecordedGateway:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def request_for_purpose(self, purpose, messages) -> LLMRequest:
        return LLMRequest(
            provider="deepinfra",
            model="Qwen/Qwen3-Max",
            messages=messages,
            purpose=purpose,
        )

    def normalize_request(self, request: LLMRequest) -> LLMRequest:
        return request

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            text=self.response_text,
        )


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def evaluate_recorded_responses(
    cases_payload: dict[str, Any],
    responses_payload: dict[str, Any],
    thresholds: dict[str, float],
    *,
    require_provider_evidence: bool = False,
) -> EvaluationReport:
    evaluation_version = _required_string(cases_payload, "evaluation_version")
    prompt_version = _required_string(cases_payload, "prompt_version")
    if prompt_version != STATE_EXTRACTION_PROMPT_VERSION:
        raise ValueError(
            f"Evaluation prompt version {prompt_version} does not match application "
            f"version {STATE_EXTRACTION_PROMPT_VERSION}"
        )
    prompt_sha256 = hashlib.sha256(STATE_EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest()
    if cases_payload.get("prompt_sha256") != prompt_sha256:
        raise ValueError("Evaluation prompt_sha256 does not match the application prompt")
    if responses_payload.get("evaluation_version") != evaluation_version:
        raise ValueError("Response bundle evaluation_version does not match the case set")
    if responses_payload.get("prompt_version") != prompt_version:
        raise ValueError("Response bundle prompt_version does not match the case set")
    expected_case_hash = hashlib.sha256(
        json.dumps(
            cases_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if responses_payload.get("case_set_sha256") != expected_case_hash:
        raise ValueError("Response bundle case_set_sha256 does not match the case set")
    evidence_kind = _required_string(responses_payload, "evidence_kind")
    if require_provider_evidence and evidence_kind != "provider_capture":
        raise ValueError("Model approval requires evidence_kind=provider_capture")
    if require_provider_evidence:
        if _required_string(responses_payload, "provider") == "synthetic":
            raise ValueError("Model approval cannot use a synthetic provider")
        if responses_payload.get("capture_method") != "bounded_live_provider":
            raise ValueError("Model approval requires capture_method=bounded_live_provider")
        captured_at = datetime.fromisoformat(
            _required_string(responses_payload, "captured_at").replace("Z", "+00:00")
        )
        if captured_at.tzinfo is None:
            raise ValueError("Model approval captured_at must include a timezone")

    cases = cases_payload.get("cases")
    responses = responses_payload.get("responses")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation case set must contain at least one case")
    if not isinstance(responses, dict):
        raise ValueError("Response bundle responses must be an object keyed by case id")
    case_ids = [_required_string(case, "id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids):
        raise ValueError("Evaluation case ids must be present and unique")
    missing = sorted(set(case_ids) - set(responses))
    extra = sorted(set(responses) - set(case_ids))
    if missing or extra:
        raise ValueError(f"Response bundle coverage mismatch; missing={missing}, extra={extra}")

    case_reports = [
        asyncio.run(_evaluate_case(case, _response_text(responses[case["id"]])))
        for case in cases
    ]
    metrics = _aggregate(case_reports)
    failures = _threshold_failures(metrics, thresholds)
    return EvaluationReport(
        evaluation_version=evaluation_version,
        prompt_version=prompt_version,
        evidence_kind=evidence_kind,
        provider=_required_string(responses_payload, "provider"),
        model=_required_string(responses_payload, "model"),
        metrics=metrics,
        thresholds=thresholds,
        passed=not failures,
        failures=failures,
        cases=case_reports,
    )


def validate_route_approval(
    cases_payload: dict[str, Any],
    thresholds: dict[str, float],
    approval: dict[str, Any],
    *,
    evaluation_root: Path,
    current_provider: str,
    current_model: str,
) -> EvaluationReport | None:
    if approval.get("evaluation_version") != cases_payload.get("evaluation_version"):
        raise ValueError("Route approval evaluation_version does not match the case set")
    if approval.get("prompt_version") != cases_payload.get("prompt_version"):
        raise ValueError("Route approval prompt_version does not match the case set")
    route = approval.get("state_update_route")
    if not isinstance(route, dict):
        raise ValueError("Route approval must contain state_update_route")
    approved_provider = _required_string(route, "provider")
    approved_model = _required_string(route, "model")
    if (approved_provider, approved_model) != (current_provider, current_model):
        raise ValueError(
            "Current state_update default does not match the evaluated route approval"
        )
    evidence_kind = _required_string(route, "evidence_kind")
    if evidence_kind == "legacy_pre_evaluation_default":
        if (approved_provider, approved_model) != LEGACY_STRUCTURED_ROUTE:
            raise ValueError(
                "The legacy exception is pinned to the pre-evaluation structured default"
            )
        return None
    if evidence_kind != "provider_capture":
        raise ValueError(f"Unsupported route approval evidence_kind={evidence_kind}")
    response_path = (evaluation_root / _required_string(route, "response_bundle")).resolve()
    resolved_root = evaluation_root.resolve()
    if not response_path.is_relative_to(resolved_root):
        raise ValueError("Route approval response_bundle must remain inside the evaluation root")
    report = evaluate_recorded_responses(
        cases_payload,
        load_json(response_path),
        thresholds,
        require_provider_evidence=True,
    )
    if report.provider != approved_provider or report.model != approved_model:
        raise ValueError("Provider capture identity does not match the approved route")
    if not report.passed:
        raise ValueError("Provider capture does not pass structured extraction thresholds")
    return report


async def _evaluate_case(case: dict[str, Any], response_text: str) -> dict[str, Any]:
    previous = StoryState.model_validate(case.get("previous_state", {}))
    result = await extract_story_updates_with_llm(
        _RecordedGateway(response_text),
        previous,
        str(case.get("user_turn", "")),
        str(case.get("assistant_turn", "")),
        relationships=case.get("previous_relationships") or [],
        perspective_character=case.get("perspective_character"),
    )
    expected = case.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(f"Case {case.get('id')} expected must be an object")
    expected_state = StoryState.model_validate(expected.get("state", {}))
    scalar_matches = {
        field: getattr(result.state, field) == getattr(expected_state, field)
        for field in ("location", "time", "mood", "objective")
    }
    collection_scores = {
        field: _set_f1(getattr(result.state, field), getattr(expected_state, field))
        for field in ("inventory", "open_threads")
    }
    collection_scores.update(
        {
            "memories": _set_f1(result.memories, expected.get("memories", [])),
            "canon_facts": _set_f1(result.canon_facts, expected.get("canon_facts", [])),
        }
    )
    relationship_f1 = _set_f1(
        [_relationship_key(item) for item in result.relationships],
        [_relationship_key(item) for item in expected.get("relationships", [])],
    )
    critical = _critical_assertions(case.get("critical_assertions", []), result)
    unexpected, predicted = _hallucination_counts(result, expected_state, expected)
    return {
        "id": case["id"],
        "parse_success": result.source == "llm",
        "actual": {
            "state": result.state.model_dump(),
            "relationships": result.relationships,
            "memories": result.memories,
            "canon_facts": result.canon_facts,
        },
        "scalar_matches": scalar_matches,
        "collection_f1": collection_scores,
        "relationship_f1": relationship_f1,
        "critical": critical,
        "unexpected_predictions": unexpected,
        "prediction_count": predicted,
    }


def _aggregate(case_reports: list[dict[str, Any]]) -> EvaluationMetrics:
    scalar_values = [
        float(value)
        for report in case_reports
        for value in report["scalar_matches"].values()
    ]
    collection_values = [
        value
        for report in case_reports
        for value in report["collection_f1"].values()
    ]
    relationship_values = [report["relationship_f1"] for report in case_reports]
    critical_values = [
        float(assertion["passed"])
        for report in case_reports
        for assertion in report["critical"]
    ]
    unexpected = sum(report["unexpected_predictions"] for report in case_reports)
    predicted = sum(report["prediction_count"] for report in case_reports)
    return EvaluationMetrics(
        case_count=len(case_reports),
        parse_success_rate=_mean([float(report["parse_success"]) for report in case_reports]),
        scalar_accuracy=_mean(scalar_values),
        collection_f1=_mean(collection_values),
        relationship_f1=_mean(relationship_values),
        critical_pass_rate=_mean(critical_values) if critical_values else 1.0,
        hallucination_rate=unexpected / predicted if predicted else 0.0,
    )


def _threshold_failures(
    metrics: EvaluationMetrics,
    thresholds: dict[str, float],
) -> list[str]:
    failures: list[str] = []
    values = asdict(metrics)
    for name, threshold in thresholds.items():
        if name == "max_hallucination_rate":
            if metrics.hallucination_rate > threshold:
                failures.append(
                    f"hallucination_rate={metrics.hallucination_rate:.4f} exceeds {threshold:.4f}"
                )
            continue
        metric_name = name.removeprefix("min_")
        value = values.get(metric_name)
        if not isinstance(value, (int, float)):
            raise ValueError(f"Unknown evaluation threshold {name}")
        if value < threshold:
            failures.append(f"{metric_name}={value:.4f} is below {threshold:.4f}")
    return failures


def _critical_assertions(assertions: Any, result: ExtractionResult) -> list[dict[str, Any]]:
    if not isinstance(assertions, list):
        raise ValueError("critical_assertions must be a list")
    payload = {
        "state": result.state.model_dump(),
        "relationships": result.relationships,
        "memories": result.memories,
        "canon_facts": result.canon_facts,
    }
    reports: list[dict[str, Any]] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            raise ValueError("Each critical assertion must be an object")
        path = _required_string(assertion, "path")
        actual = _path_value(payload, path)
        expected = assertion.get("equals")
        reports.append({"path": path, "passed": actual == expected})
    return reports


def _path_value(payload: Any, path: str) -> Any:
    current = payload
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _hallucination_counts(
    result: ExtractionResult,
    expected_state: StoryState,
    expected: dict[str, Any],
) -> tuple[int, int]:
    unexpected = 0
    predicted = 0
    for field in ("location", "time", "mood", "objective"):
        actual = getattr(result.state, field)
        predicted += int(bool(actual))
        unexpected += int(actual != getattr(expected_state, field))
    pairs = (
        (result.state.inventory, expected_state.inventory),
        (result.state.open_threads, expected_state.open_threads),
        (result.memories, expected.get("memories", [])),
        (result.canon_facts, expected.get("canon_facts", [])),
        (
            [_relationship_key(item) for item in result.relationships],
            [_relationship_key(item) for item in expected.get("relationships", [])],
        ),
    )
    for actual, wanted in pairs:
        actual_set = set(actual)
        predicted += len(actual_set)
        unexpected += len(actual_set - set(wanted))
    return unexpected, predicted


def _relationship_key(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    return "|".join(
        str(item.get(field, "")) for field in ("from", "to", "bond", "value")
    )


def _set_f1(actual: list[Any], expected: list[Any]) -> float:
    actual_set = set(actual)
    expected_set = set(expected)
    if not actual_set and not expected_set:
        return 1.0
    if not actual_set or not expected_set:
        return 0.0
    true_positive = len(actual_set & expected_set)
    precision = true_positive / len(actual_set)
    recall = true_positive / len(expected_set)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _response_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Every recorded response must be a string")
    return value
