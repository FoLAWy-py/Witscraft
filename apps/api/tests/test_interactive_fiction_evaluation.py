import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evals.interactive_fiction import (
    build_judge_request,
    canonical_sha256,
    evaluate_provider_capture,
)
from app.services.style_profiles import (
    analyze_style_features,
    public_style_features,
    reference_content_hash,
)


EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals" / "interactive_fiction" / "v1"


def _load(name: str) -> dict:
    return json.loads((EVAL_ROOT / name).read_text(encoding="utf-8"))


def _generated_chapter() -> str:
    dialogue = "“The household answers with a precise external fact and leaves the choice open.”"
    narration = (
        "The rainbound room changes through observable reactions while the player remains still."
    )
    paragraphs = [dialogue if index % 2 == 0 else narration for index in range(40)]
    return "\n\n".join(paragraphs)


def _capture(case: dict, chapter: str) -> dict:
    generated_features = public_style_features(
        analyze_style_features(chapter, "en", reference_content_hash(chapter))
    )
    return {
        "schema_version": 1,
        "evaluation_version": case["evaluation_version"],
        "case_sha256": canonical_sha256(case),
        "evidence_kind": "provider_capture",
        "capture_method": "bounded_live_provider_end_to_end",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "deployment_revision": "a" * 40,
        "reference_source_url": case["reference"]["source_url"],
        "profile_reused": True,
        "abstract_profile": case["reference"]["expected_abstract_features"],
        "author": {"provider": "deepinfra", "model": "Qwen/Qwen3-Max"},
        "judge": {
            "provider": "openai",
            "model": "gpt-5.5",
            "prompt_version": case["judge_prompt_version"],
        },
        "calls": {
            "call_limit": 8,
            "profiling_calls": 0,
            "lifecycle_calls": 6,
            "judge_calls": 1,
            "lifecycle_routes": [
                "deepinfra:Qwen/Qwen3-Max:normal_chat",
                "deepinfra:Qwen/Qwen3-Max:normal_chat",
                "deepinfra:Qwen/Qwen3-Max:normal_chat",
                "openai:gpt-5.5:consistency_check",
                "deepinfra:Qwen/Qwen3-Max:state_update",
                "deepinfra:Qwen/Qwen3-Max:normal_chat",
            ],
        },
        "generated_chapter": chapter,
        "generated_chapter_sha256": hashlib.sha256(chapter.encode()).hexdigest(),
        "generated_features": generated_features,
        "scores": {
            "profile_adherence": 90,
            "narrative_quality": 90,
            "player_agency": 95,
            "world_canon": 90,
            "roadmap_length": 95,
            "overall": 92,
            "reasons": ["Synthetic contract response for evaluator tests."],
        },
    }


def test_provider_capture_replay_reports_provider_scores_and_deterministic_gates() -> None:
    case = _load("case.json")
    reference = (EVAL_ROOT / "reference.txt").read_text(encoding="utf-8")
    chapter = _generated_chapter()
    capture = _capture(case, chapter)
    thresholds = {
        key: float(value) for key, value in _load("thresholds.json")["thresholds"].items()
    }

    report = evaluate_provider_capture(case, reference, capture, thresholds)

    assert report.passed is True
    assert report.score_source == "provider_capture"
    assert report.scores["player_agency"] == 95
    assert report.measurements["within_length_band"] is True
    assert report.measurements["reference_overlap_blocked"] is False
    assert report.measurements["provider_calls"] == 7


def test_reviewed_real_provider_capture_passes_current_gate() -> None:
    case = _load("case.json")
    reference = (EVAL_ROOT / "reference.txt").read_text(encoding="utf-8")
    thresholds = {
        key: float(value) for key, value in _load("thresholds.json")["thresholds"].items()
    }

    report = evaluate_provider_capture(
        case,
        reference,
        _load("provider-capture.json"),
        thresholds,
    )

    assert report.passed is True
    assert report.score_source == "provider_capture"
    assert report.scores == {
        "profile_adherence": 74,
        "narrative_quality": 86,
        "player_agency": 94,
        "world_canon": 88,
        "roadmap_length": 96,
        "overall": 86,
    }
    assert report.measurements["measured_length"] == 574
    assert report.measurements["provider_calls"] == 8


def test_evaluator_rejects_synthetic_or_tampered_model_score_evidence() -> None:
    case = _load("case.json")
    reference = (EVAL_ROOT / "reference.txt").read_text(encoding="utf-8")
    capture = _capture(case, _generated_chapter())

    capture["evidence_kind"] = "synthetic_contract"
    with pytest.raises(ValueError, match="provider_capture"):
        evaluate_provider_capture(case, reference, capture, {})

    capture = _capture(case, _generated_chapter())
    capture["generated_features"]["dialogue_ratio"] = 0.0
    with pytest.raises(ValueError, match="features"):
        evaluate_provider_capture(case, reference, capture, {})


def test_judge_contract_uses_only_abstract_profile_and_generated_prose() -> None:
    case = _load("case.json")
    abstract_profile = case["reference"]["expected_abstract_features"]
    request = build_judge_request(case, abstract_profile, abstract_profile, "Original prose.")

    assert request.provider == "openai"
    assert request.model == "gpt-5.5"
    assert request.response_format == "json"
    assert "json" in request.messages[0].content
    payload = json.loads(request.messages[1].content)
    assert payload["abstract_profile"] == abstract_profile
    assert payload["generated_chapter"] == "Original prose."
    assert "Pride and Prejudice" not in request.model_dump_json()
    assert case["reference"]["source_url"] not in request.model_dump_json()
