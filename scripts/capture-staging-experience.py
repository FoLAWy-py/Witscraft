#!/usr/bin/env python3
"""Run a bounded, sanitized real-provider journey against isolated LAN staging."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps/api"
CASE_ROOT = API_ROOT / "evals/interactive_fiction/v1"
MAX_PROVIDER_CALLS = 12
JUDGE_PROMPT_VERSION = "staging-multiturn-experience-judge-v2"
SCORE_THRESHOLDS = {
    "profile_adherence": 65,
    "narrative_quality": 80,
    "player_agency": 90,
    "world_canon": 80,
    "narrative_pacing": 85,
    "overall": 80,
}
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.models import AuthCredential, ModelCall, User  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.llm.openai_adapter import OpenAIAdapter  # noqa: E402
from app.schemas.llm import ChatMessage, LLMRequest  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.services.player_agency import chapter_prose  # noqa: E402
from app.services.style_profiles import reference_content_hash  # noqa: E402
from app.services.style_profiles import (  # noqa: E402
    analyze_style_features,
    assert_non_reproducing,
    public_style_features,
)


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
        raise ValueError("Staging capture requires a credential-free HTTPS base URL")
    return f"{value.rstrip('/')}/"


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _word_count(text: str) -> int:
    return len([word for word in chapter_prose(text).split() if word])


def _judge_request(
    *,
    settings,
    scenario: dict[str, Any],
    abstract_profile: dict[str, Any],
    generated_features: dict[str, Any],
    turns: list[dict[str, Any]],
) -> LLMRequest:
    payload = {
        "prompt_version": JUDGE_PROMPT_VERSION,
        "scenario": {
            key: scenario[key]
            for key in (
                "title",
                "genre",
                "world_name",
                "premise",
                "protagonist_name",
                "protagonist_role",
                "tone",
                "custom_prompt",
            )
        },
        "abstract_profile": abstract_profile,
        "generated_features": generated_features,
        "ordered_turns": turns,
        "rubric": {
            "profile_adherence": (
                "Abstract stylistic feature adherence without author imitation or phrase copying."
            ),
            "narrative_quality": "Prose, dialogue, dramatic clarity, and chapter readability.",
            "player_agency": (
                "For player_action, the AI may narrate consequences but must not invent new "
                "protagonist speech, choices, or thoughts beyond that turn's supplied action. "
                "For continue, the player explicitly authorizes the AI to advance the protagonist "
                "for that turn only. Later player turns are new authoritative decisions and must "
                "not be judged against an earlier turn's action."
            ),
            "world_canon": "Continuity across the ordered turns and consistency with the premise.",
            "narrative_pacing": (
                "Interactive progression across turns: each installment is proportionate to its "
                "player input, moves through a causal scene beat, varies its pressure or stopping "
                "device, and reaches a useful decision point. Chapter length is only a minimum and "
                "reaching it must not force closure. Stylistic speed such as fast versus moderate "
                "belongs only to profile_adherence and must not be deducted again here."
            ),
        },
    }
    return LLMRequest(
        provider="openai",
        model=settings.default_openai_model,
        purpose="consistency_check",
        messages=[
            ChatMessage(
                role="developer",
                content=(
                    "Evaluate this multi-turn AI-authored interactive-novel experience. Score each "
                    "named dimension and overall from 0 to 100. Bind every installment only to its "
                    "matching player input and control_mode. Keep profile_adherence and narrative_pacing "
                    "orthogonal; do not double-penalize a stylistic speed mismatch. Return one JSON object containing the "
                    "five dimension keys, overall, and a reasons array. Do not reproduce the prose."
                ),
            ),
            ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
        max_output_tokens=1600,
        response_format="json",
        temperature=0.2,
        top_p=0.9,
        reasoning_effort="medium",
    )


def _score_failures(scores: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for name, threshold in SCORE_THRESHOLDS.items():
        value = scores.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ValueError(f"Provider judge returned invalid {name}")
        if value < threshold:
            failures.append(f"{name}={value} is below {threshold}")
    reasons = scores.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(
        isinstance(reason, str) and reason.strip() for reason in reasons
    ):
        raise ValueError("Provider judge must return non-empty reasons")
    return failures


async def _model_calls(user_id: UUID) -> list[ModelCall]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(ModelCall)
                    .where(ModelCall.user_id == user_id)
                    .order_by(ModelCall.created_at, ModelCall.id)
                )
            ).all()
        )


async def _stream_turn(
    client: httpx.AsyncClient,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    first_content_ms: int | None = None
    done_response: dict[str, Any] | None = None
    event_type = "message"
    data_lines: list[str] = []

    async with client.stream("POST", "api/chat/stream", json=payload, headers=headers) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
            elif not line and data_lines:
                event = json.loads("\n".join(data_lines))
                data_lines = []
                if event_type in {"delta", "replace"} and first_content_ms is None:
                    first_content_ms = round((time.perf_counter() - started) * 1000)
                if event_type == "error":
                    raise RuntimeError(f"Stream failed with status {event.get('status')}")
                if event_type == "done":
                    candidate = event.get("response")
                    if not isinstance(candidate, dict):
                        raise RuntimeError("Stream done event omitted the response payload")
                    done_response = candidate
                event_type = "message"

    if done_response is None or first_content_ms is None:
        raise RuntimeError("Stream did not provide both visible content and a done response")
    return done_response, first_content_ms


async def _capture(args: argparse.Namespace) -> dict[str, Any]:
    case = _load_object(args.case)
    scenario = case["scenario"]
    reference_meta = case["reference"]
    reference_path = (args.case.parent / reference_meta["path"]).resolve()
    if not reference_path.is_relative_to(args.case.parent.resolve()):
        raise ValueError("Reference path must remain inside the reviewed evaluation directory")
    reference_text = reference_path.read_text(encoding="utf-8")
    if reference_content_hash(reference_text) != reference_meta["normalized_sha256"]:
        raise ValueError("Reviewed public-domain reference hash does not match")

    settings = get_settings()
    if settings.dry_run_llm:
        raise RuntimeError("Real-provider staging capture refuses DRY_RUN_LLM=true")
    if settings.llm_max_attempts != 1 or settings.llm_max_fallbacks != 0:
        raise RuntimeError("Bounded capture requires one attempt and zero fallbacks")
    if not settings.openai_api_key or not settings.deepinfra_api_key:
        raise RuntimeError("Both approved provider credentials are required")

    marker = uuid4().hex
    email = f"staging-experience-{marker}@example.invalid"
    password = secrets.token_urlsafe(32)
    user_id: UUID | None = None
    tls_context = ssl.create_default_context(cafile=args.ca_file)
    turn_summaries: list[dict[str, Any]] = []
    judge_turns: list[dict[str, Any]] = []
    generated_installments: list[str] = []
    try:
        async with AsyncSessionLocal() as session:
            user = User(
                email=email,
                display_name="Staging Experience Probe",
                email_verified_at=datetime.now(timezone.utc),
                is_admin=False,
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            session.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
            await session.commit()

        origin_parts = urlsplit(args.base_url)
        origin = f"{origin_parts.scheme}://{origin_parts.netloc}"
        headers = {"Origin": origin}
        async with httpx.AsyncClient(
            base_url=args.base_url,
            timeout=httpx.Timeout(args.timeout, connect=20.0),
            verify=tls_context,
            headers=headers,
        ) as client:
            login = await client.post(
                "api/auth/login",
                json={
                    "email": email,
                    "password": password,
                    "device_name": "Bounded LAN staging experience",
                },
            )
            login.raise_for_status()
            quota_before_response = await client.get("api/quota/me")
            quota_before_response.raise_for_status()
            quota_before = quota_before_response.json()

            profile_request = {
                "name": "Reviewed public-domain abstract profile",
                "source_type": "public_domain",
                "source_label": f"{reference_meta['source_title']}; {reference_meta['source_url']}",
                "language": reference_meta["language"],
                "raw_text": reference_text,
                "rights_attested": True,
            }
            profiled = await client.post("api/workspace/style-profiles", json=profile_request)
            profiled.raise_for_status()
            repeated = await client.post("api/workspace/style-profiles", json=profile_request)
            repeated.raise_for_status()
            if repeated.json().get("id") != profiled.json().get("id") or not repeated.json().get(
                "reused"
            ):
                raise RuntimeError("Unchanged reference profile was not reused")
            if await _model_calls(user_id):
                raise RuntimeError("Local style profiling unexpectedly contacted a provider")

            create_payload = {
                key: scenario[key]
                for key in (
                    "title",
                    "genre",
                    "world_name",
                    "premise",
                    "protagonist_name",
                    "protagonist_role",
                    "tone",
                    "opening_text",
                    "custom_prompt",
                    "interaction_mode",
                    "planned_chapter_count",
                    "minimum_chapter_length",
                    "chapter_length_unit",
                    "prose_language",
                )
            }
            create_payload.update(
                {
                    "opening_mode": "custom",
                    "style_profile_id": profiled.json()["id"],
                }
            )
            created = await client.post("api/workspace/stories", json=create_payload)
            created.raise_for_status()
            workspace = created.json()
            story_id = workspace["story_id"]
            branch_id = workspace["branch_id"]
            branch_version = 0

            turns = (
                (
                    scenario["player_action"],
                    "player_action",
                    False,
                ),
                (
                    "Continue. Advance Eleanor only for this turn while preserving the unresolved letter mystery.",
                    "continue",
                    True,
                ),
                (
                    "I address the room: 'Let the intended recipient step forward,' and remain where I am.",
                    "player_action",
                    False,
                ),
            )
            for index, (message, control_mode, streamed) in enumerate(turns, start=1):
                key = f"staging-experience-{marker}-{index}"
                request_payload = {
                    "message": message,
                    "story_id": story_id,
                    "branch_id": branch_id,
                    "branch_version": branch_version,
                    "control_mode": control_mode,
                    "idempotency_key": key,
                }
                request_headers = {**headers, "Idempotency-Key": key}
                if streamed:
                    response_payload, client_first_content_ms = await _stream_turn(
                        client,
                        payload=request_payload,
                        headers=request_headers,
                    )
                else:
                    generated = await client.post(
                        "api/chat/send",
                        json=request_payload,
                        headers=request_headers,
                    )
                    generated.raise_for_status()
                    response_payload = generated.json()
                    client_first_content_ms = None
                content = response_payload.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError(f"Turn {index} returned no narrative content")
                branch_version = int(response_payload["branch_version"])
                transition = response_payload.get("chapter_transition") or {}
                turn_summaries.append(
                    {
                        "turn": index,
                        "control_mode": control_mode,
                        "streamed": streamed,
                        "client_first_content_ms": client_first_content_ms,
                        "words": _word_count(content),
                        "chapter_completed": bool(transition.get("completed", False)),
                        "chapter_number": transition.get("chapter_number"),
                        "next_chapter_number": transition.get("next_chapter_number"),
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    }
                )
                generated_installments.append(content)
                judge_turns.append(
                    {
                        "turn": index,
                        "control_mode": control_mode,
                        "player_input": message,
                        "ai_installment": content,
                        "chapter_completed": bool(transition.get("completed", False)),
                    }
                )
                lifecycle_calls = await _model_calls(user_id)
                if len(lifecycle_calls) >= MAX_PROVIDER_CALLS:
                    raise RuntimeError("Lifecycle exhausted the provider cap before independent judging")

            if turn_summaries[0]["chapter_completed"]:
                raise RuntimeError("The first installment closed the chapter mechanically")
            lifecycle_calls = await _model_calls(user_id)
            if len(lifecycle_calls) + 1 > MAX_PROVIDER_CALLS:
                raise RuntimeError("Lifecycle plus judge would exceed the 12-call hard cap")
            if any(call.status != "succeeded" for call in lifecycle_calls):
                raise RuntimeError("At least one audited lifecycle provider call failed")
            if any((call.response or {}).get("dry_run") for call in lifecycle_calls):
                raise RuntimeError("A lifecycle model call was simulated")

            combined_prose = "\n\n".join(generated_installments)
            profile_payload = profiled.json()
            assert_non_reproducing(
                combined_prose,
                profile_payload["content_hash"],
                profile_payload["features"],
            )
            generated_features = public_style_features(
                analyze_style_features(
                    combined_prose,
                    scenario["prose_language"],
                    reference_content_hash(combined_prose),
                )
            )
            judge_request = _judge_request(
                settings=settings,
                scenario=scenario,
                abstract_profile=profile_payload["features"],
                generated_features=generated_features,
                turns=judge_turns,
            )
            judged = await OpenAIAdapter(settings).generate(judge_request)
            scores = json.loads(judged.text)
            if not isinstance(scores, dict):
                raise RuntimeError("Independent provider judge returned invalid scores")
            score_failures = _score_failures(scores)

            quota_after_response = await client.get("api/quota/me")
            quota_after_response.raise_for_status()
            quota_after = quota_after_response.json()
            workspace_after_response = await client.get("api/workspace")
            workspace_after_response.raise_for_status()
            workspace_after = workspace_after_response.json()

        provider_calls = [
            {
                "provider": call.provider,
                "model": call.model,
                "purpose": call.purpose,
                "status": call.status,
                "latency_ms": call.latency_ms,
                "first_token_latency_ms": call.first_token_latency_ms,
                "completion_status": (call.response or {}).get("completion_status"),
            }
            for call in lifecycle_calls
        ]
        active_chapters = [
            chapter["number"]
            for chapter in workspace_after.get("chapters", [])
            if chapter.get("status") == "active"
        ]
        return {
            "schema_version": "staging-provider-experience-v1",
            "evidence_kind": "bounded_live_provider_experience",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "deployment_revision": subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "capture_environment": "isolated_lan_staging_https",
            "provider_call_limit": MAX_PROVIDER_CALLS,
            "provider_calls_used": len(lifecycle_calls) + 1,
            "lifecycle_calls": provider_calls,
            "judge": {
                "provider": judged.provider,
                "model": judged.model,
                "prompt_version": JUDGE_PROMPT_VERSION,
                "scores": scores,
                "thresholds": SCORE_THRESHOLDS,
                "passed": not score_failures,
                "failures": score_failures,
            },
            "turns": turn_summaries,
            "chapter_state": {
                "active_chapter_numbers": active_chapters,
                "transition_count": sum(turn["chapter_completed"] for turn in turn_summaries),
            },
            "quota_percentage": {
                "before": quota_before["percentage_used"],
                "after": quota_after["percentage_used"],
                "scope": "account_week",
            },
            "style_profile_reused_without_provider_call": True,
            "temporary_account_cleanup_required": True,
        }
    finally:
        if user_id is not None:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
                remaining = await session.scalar(
                    select(func.count()).select_from(User).where(User.id == user_id)
                )
                if remaining:
                    raise RuntimeError("Temporary staging experience account cleanup failed")
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", type=_safe_https_url)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--case", type=Path, default=CASE_ROOT / "case.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".runtime/staging/provider-experience.json",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--confirm-live-provider", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_provider:
        parser.error("--confirm-live-provider is required")
    if not args.ca_file.is_file():
        parser.error("--ca-file must be a readable certificate")
    output = args.output.expanduser().resolve()
    runtime_root = (ROOT / ".runtime").resolve()
    if not output.is_relative_to(runtime_root):
        parser.error("--output must remain inside the ignored .runtime directory")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        result = asyncio.run(_capture(args))
        result["temporary_account_cleanup_verified"] = True
        result.pop("temporary_account_cleanup_required", None)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(output)
    except Exception as error:
        print(f"Staging provider experience failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(
        "Staging provider experience completed: "
        f"calls={result['provider_calls_used']}/{MAX_PROVIDER_CALLS}, "
        f"turns={len(result['turns'])}, overall={result['judge']['scores']['overall']}"
    )
    print(f"Sanitized evidence: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
