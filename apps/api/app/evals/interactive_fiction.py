from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.schemas.llm import ChatMessage, LLMRequest
from app.services.player_agency import (
    CHAPTER_AUTHORING_PROMPT_VERSION,
    PLAYER_AGENCY_EDITOR_PROMPT_VERSION,
    chapter_prose,
    measured_chapter_length,
)
from app.services.style_profiles import (
    STYLE_ANALYSIS_VERSION,
    STYLE_PROMPT_VERSION,
    STYLE_SAFETY_VERSION,
    analyze_style_features,
    evaluate_reference_overlap,
    public_style_features,
    reference_content_hash,
)


JUDGE_PROMPT_VERSION = "interactive-fiction-judge-v4"
SCORE_NAMES = (
    "profile_adherence",
    "narrative_quality",
    "player_agency",
    "world_canon",
    "narrative_pacing",
    "overall",
)


@dataclass(frozen=True)
class InteractiveFictionEvaluationReport:
    evaluation_version: str
    evidence_kind: str
    score_source: str
    author_provider: str
    author_model: str
    judge_provider: str
    judge_model: str
    scores: dict[str, int]
    measurements: dict[str, Any]
    thresholds: dict[str, float]
    passed: bool
    failures: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def build_judge_request(
    case_payload: dict[str, Any],
    abstract_profile: dict[str, Any],
    generated_profile: dict[str, Any],
    generated_chapter: str,
    chapter_transition: dict[str, Any] | None = None,
) -> LLMRequest:
    scenario = _required_dict(case_payload, "scenario")
    payload = {
        "abstract_profile": abstract_profile,
        "measured_generated_profile": generated_profile,
        "player_action": _required_string(scenario, "player_action"),
        "minimum_chapter_words": int(scenario["minimum_chapter_length"]),
        "generated_installment": generated_chapter,
        "chapter_transition": chapter_transition or {"completed": False},
    }
    return LLMRequest(
        provider="openai",
        model="gpt-5.5",
        purpose="consistency_check",
        response_format="json",
        max_output_tokens=1200,
        temperature=0.2,
        top_p=0.8,
        reasoning_effort="medium",
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You are an independent interactive-fiction evaluator. Score only the supplied "
                    "generated installment against the abstract style profile and explicit product "
                    "contract. Do not infer or reward resemblance to any named author. Return json "
                    "only with integer scores from 0 to 100 for profile_adherence, "
                    "narrative_quality, player_agency, world_canon, narrative_pacing, and overall, "
                    "plus a concise reasons array. The player action must not be expanded into "
                    "unrequested protagonist speech, thought, consent, or decisions. Judge pacing "
                    "by dramatic development, proportionality to the supplied player action, and "
                    "the natural player decision point, never by proximity to a target word count. "
                    "An installment ending returns control to the player and is not a chapter ending. "
                    "A chapter may span many installments. Apply the supplied minimum only when "
                    "chapter_transition.completed is true; never penalize a shorter installment when "
                    "it is false. Keep profile_adherence and narrative_pacing orthogonal: stylistic "
                    "speed such as fast versus moderate belongs only to profile_adherence and must "
                    "not be deducted again from pacing. There is no target or maximum chapter or "
                    "installment length."
                ),
            ),
            ChatMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        ],
    )


def evaluate_provider_capture(
    case_payload: dict[str, Any],
    reference_text: str,
    capture_payload: dict[str, Any],
    thresholds: dict[str, float],
) -> InteractiveFictionEvaluationReport:
    evaluation_version = _required_string(case_payload, "evaluation_version")
    if capture_payload.get("evaluation_version") != evaluation_version:
        raise ValueError("Capture evaluation_version does not match the case")
    if capture_payload.get("case_sha256") != canonical_sha256(case_payload):
        raise ValueError("Capture case_sha256 does not match the case")
    if capture_payload.get("evidence_kind") != "provider_capture":
        raise ValueError("Interactive-fiction model scores require provider_capture evidence")
    if capture_payload.get("capture_method") != "bounded_live_provider_end_to_end":
        raise ValueError("Capture method is not the bounded end-to-end provider workflow")
    captured_at = datetime.fromisoformat(
        _required_string(capture_payload, "captured_at").replace("Z", "+00:00")
    )
    if captured_at.tzinfo is None:
        raise ValueError("Capture timestamp must include a timezone")
    if not re.fullmatch(r"[0-9a-f]{40}", _required_string(capture_payload, "deployment_revision")):
        raise ValueError("Capture deployment_revision must be one full lowercase Git SHA")

    _validate_prompt_versions(case_payload)
    reference = _required_dict(case_payload, "reference")
    normalized_reference_hash = reference_content_hash(reference_text)
    if normalized_reference_hash != _required_string(reference, "normalized_sha256"):
        raise ValueError("Reference content hash does not match the reviewed case")
    reference_features = analyze_style_features(
        reference_text,
        _required_string(reference, "language"),
        normalized_reference_hash,
    )
    abstract_profile = public_style_features(reference_features)
    if abstract_profile != _required_dict(reference, "expected_abstract_features"):
        raise ValueError("Reference abstract profile drifted from the reviewed case")
    if _required_dict(capture_payload, "abstract_profile") != abstract_profile:
        raise ValueError("Captured abstract profile does not match the reviewed reference")
    if capture_payload.get("reference_source_url") != reference.get("source_url"):
        raise ValueError("Capture reference provenance does not match the reviewed case")

    generated_chapter = _required_string(capture_payload, "generated_chapter")
    if (
        capture_payload.get("generated_chapter_sha256")
        != hashlib.sha256(generated_chapter.encode()).hexdigest()
    ):
        raise ValueError("Generated chapter hash does not match capture content")
    scenario = _required_dict(case_payload, "scenario")
    prose = chapter_prose(generated_chapter)
    generated_features = public_style_features(
        analyze_style_features(
            prose,
            _required_string(scenario, "prose_language"),
            reference_content_hash(prose),
        )
    )
    if generated_features != _required_dict(capture_payload, "generated_features"):
        raise ValueError("Captured generated features do not match deterministic analysis")
    overlap = evaluate_reference_overlap(
        generated_chapter,
        normalized_reference_hash,
        reference_features.get("_safety"),
    )
    if overlap.blocked:
        raise ValueError("Provider capture reproduces the reference too closely")

    scores_payload = _required_dict(capture_payload, "scores")
    scores: dict[str, int] = {}
    for score_name in SCORE_NAMES:
        value = scores_payload.get(score_name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ValueError(f"Capture has invalid {score_name} score")
        scores[score_name] = value
    reasons = scores_payload.get("reasons")
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(reason, str) and reason.strip() for reason in reasons)
    ):
        raise ValueError("Capture scores require non-empty provider judge reasons")

    calls = _required_dict(capture_payload, "calls")
    call_limit = int(case_payload["call_limit"])
    lifecycle_calls = int(calls.get("lifecycle_calls", -1))
    judge_calls = int(calls.get("judge_calls", -1))
    total_calls = lifecycle_calls + judge_calls
    routes = calls.get("lifecycle_routes")
    if not isinstance(routes, list) or len(routes) != lifecycle_calls:
        raise ValueError("Capture lifecycle routes do not match lifecycle call count")
    if not 1 <= lifecycle_calls <= call_limit - 1 or judge_calls != 1:
        raise ValueError("Capture call counts violate the bounded workflow")
    if total_calls > call_limit:
        raise ValueError("Capture exceeds the provider call limit")
    if int(calls.get("call_limit", -1)) != call_limit:
        raise ValueError("Capture call_limit does not match the reviewed case")
    if int(calls.get("profiling_calls", -1)) != 0:
        raise ValueError("Reference profiling must not call a model")
    if capture_payload.get("profile_reused") is not True:
        raise ValueError("Capture must prove version-compatible profile reuse")

    minimum_length = int(scenario["minimum_chapter_length"])
    length_unit = _required_string(scenario, "chapter_length_unit")
    measured_length = measured_chapter_length(prose, length_unit)
    narrative_completion = _required_dict(capture_payload, "narrative_completion")
    completion_status = _required_string(narrative_completion, "status")
    if completion_status != "completed":
        raise ValueError("Provider capture narrative output is not complete")
    chapter_transition = capture_payload.get("chapter_transition")
    if chapter_transition is not None and not isinstance(chapter_transition, dict):
        raise ValueError("Capture chapter_transition must be an object or null")
    dialogue_error = abs(
        float(abstract_profile["dialogue_ratio"]) - float(generated_features["dialogue_ratio"])
    )
    measurements = {
        "minimum_chapter_length": minimum_length,
        "length_unit": length_unit,
        "measured_installment_length": measured_length,
        "output_complete": True,
        "continued_after_length_limit": bool(
            narrative_completion.get("continued_after_length_limit", False)
        ),
        "chapter_transition_completed": bool(
            chapter_transition and chapter_transition.get("completed")
        ),
        "reference_overlap_blocked": overlap.blocked,
        "reference_character_overlap_ratio": overlap.character_ratio,
        "reference_word_overlap_ratio": overlap.word_ratio,
        "reference_dialogue_ratio": abstract_profile["dialogue_ratio"],
        "generated_dialogue_ratio": generated_features["dialogue_ratio"],
        "dialogue_ratio_error": round(dialogue_error, 3),
        "provider_calls": total_calls,
        "profiling_calls": 0,
    }
    failures = _threshold_failures(scores, measurements, thresholds)
    author = _required_dict(capture_payload, "author")
    judge = _required_dict(capture_payload, "judge")
    expected_routes = _required_dict(case_payload, "expected_routes")
    expected_author = _required_dict(expected_routes, "author")
    expected_editor = _required_dict(expected_routes, "agency_editor")
    expected_judge = _required_dict(expected_routes, "judge")
    author_identity = {
        "provider": _required_string(author, "provider"),
        "model": _required_string(author, "model"),
    }
    judge_identity = {
        "provider": _required_string(judge, "provider"),
        "model": _required_string(judge, "model"),
    }
    if author_identity != expected_author:
        raise ValueError("Capture author route does not match the reviewed case")
    if judge_identity != expected_judge:
        raise ValueError("Capture judge route does not match the reviewed case")
    if judge.get("prompt_version") != case_payload.get("judge_prompt_version"):
        raise ValueError("Capture judge prompt version does not match the reviewed case")
    editor_route = (
        f"{_required_string(expected_editor, 'provider')}:"
        f"{_required_string(expected_editor, 'model')}:"
        f"{_required_string(expected_editor, 'purpose')}"
    )
    if editor_route not in routes:
        raise ValueError("Capture does not include the required player-agency editor route")
    return InteractiveFictionEvaluationReport(
        evaluation_version=evaluation_version,
        evidence_kind="provider_capture",
        score_source="provider_capture",
        author_provider=author_identity["provider"],
        author_model=author_identity["model"],
        judge_provider=judge_identity["provider"],
        judge_model=judge_identity["model"],
        scores=scores,
        measurements=measurements,
        thresholds=thresholds,
        passed=not failures,
        failures=failures,
    )


def _validate_prompt_versions(case_payload: dict[str, Any]) -> None:
    expected = {
        "chapter_authoring": CHAPTER_AUTHORING_PROMPT_VERSION,
        "player_agency_editor": PLAYER_AGENCY_EDITOR_PROMPT_VERSION,
        "style_prompt": STYLE_PROMPT_VERSION,
    }
    if _required_dict(case_payload, "prompt_versions") != expected:
        raise ValueError("Interactive-fiction prompt version drift")
    if case_payload.get("judge_prompt_version") != JUDGE_PROMPT_VERSION:
        raise ValueError("Interactive-fiction judge prompt version drift")
    if case_payload.get("style_analysis_version") != STYLE_ANALYSIS_VERSION:
        raise ValueError("Style analysis version drift")
    if case_payload.get("style_safety_version") != STYLE_SAFETY_VERSION:
        raise ValueError("Style safety version drift")


def _threshold_failures(
    scores: dict[str, int],
    measurements: dict[str, Any],
    thresholds: dict[str, float],
) -> list[str]:
    failures: list[str] = []
    for name, threshold in thresholds.items():
        if name == "max_dialogue_ratio_error":
            value = float(measurements["dialogue_ratio_error"])
            if value > threshold:
                failures.append(f"dialogue_ratio_error={value:.3f} exceeds {threshold:.3f}")
            continue
        score_name = name.removeprefix("min_")
        if score_name not in scores:
            raise ValueError(f"Unknown interactive-fiction threshold {name}")
        if scores[score_name] < threshold:
            failures.append(f"{score_name}={scores[score_name]} is below {threshold:g}")
    return failures


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Interactive-fiction evidence requires object {key}")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Interactive-fiction evidence requires non-empty {key}")
    return value
