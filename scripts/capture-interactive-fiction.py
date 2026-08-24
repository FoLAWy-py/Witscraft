#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
DEFAULT_ROOT = API_ROOT / "evals" / "interactive_fiction" / "v1"
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.models import AuthCredential, ModelCall, StyleProfile, User  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.evals.interactive_fiction import (  # noqa: E402
    build_judge_request,
    canonical_sha256,
)
from app.llm.openai_adapter import OpenAIAdapter  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.services.player_agency import chapter_prose  # noqa: E402
from app.services.style_profiles import (  # noqa: E402
    analyze_style_features,
    assert_non_reproducing,
    public_style_features,
    reference_content_hash,
)


MAX_PROVIDER_CALLS = 8


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _safe_base_url(value: str, allow_http_loopback: bool) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain credentials, query parameters, or fragments")
    if parsed.scheme == "https" and parsed.netloc:
        return f"{value.rstrip('/')}/"
    if (
        allow_http_loopback
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        return f"{value.rstrip('/')}/"
    raise ValueError("Capture target must use HTTPS; HTTP requires explicit loopback approval")


def _origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Capture case requires object {key}")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Capture case requires non-empty {key}")
    return value


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


async def _capture(args: argparse.Namespace) -> dict[str, Any]:
    case_payload = _load_object(args.case)
    if int(case_payload.get("call_limit", -1)) != MAX_PROVIDER_CALLS:
        raise ValueError(f"Case call_limit must equal the hard cap of {MAX_PROVIDER_CALLS}")
    reference_meta = _required_dict(case_payload, "reference")
    reference_path = (args.case.parent / _required_string(reference_meta, "path")).resolve()
    if not reference_path.is_relative_to(args.case.parent.resolve()):
        raise ValueError("Reference path must remain inside the evaluation directory")
    reference_text = reference_path.read_text(encoding="utf-8")
    if reference_content_hash(reference_text) != _required_string(
        reference_meta, "normalized_sha256"
    ):
        raise ValueError("Reference text does not match the reviewed case")
    scenario = _required_dict(case_payload, "scenario")
    settings = get_settings()
    if settings.dry_run_llm:
        raise RuntimeError("Live interactive-fiction capture refuses DRY_RUN_LLM=true")
    if not settings.openai_api_key or not settings.deepinfra_api_key:
        raise RuntimeError("Both OpenAI and DeepInfra must be configured for this capture")

    marker = uuid4().hex
    email = f"style-capture-{marker}@example.invalid"
    password = secrets.token_urlsafe(32)
    user_id: UUID | None = None
    try:
        async with AsyncSessionLocal() as session:
            user = User(
                email=email,
                display_name="Interactive Fiction Capture",
                email_verified_at=datetime.now(timezone.utc),
                is_admin=True,
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            session.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
            await session.commit()

        headers = {"Origin": _origin(args.base_url)}
        async with httpx.AsyncClient(
            base_url=args.base_url,
            timeout=httpx.Timeout(args.timeout, connect=20.0),
            headers=headers,
        ) as client:
            login = await client.post(
                "api/auth/login",
                json={
                    "email": email,
                    "password": password,
                    "device_name": "Bounded provider capture",
                },
            )
            login.raise_for_status()
            profile_request = {
                "name": "Reviewed public-domain dialogue profile",
                "source_type": "public_domain",
                "source_label": (
                    f"{_required_string(reference_meta, 'source_title')}; "
                    f"{_required_string(reference_meta, 'source_url')}"
                ),
                "language": _required_string(reference_meta, "language"),
                "raw_text": reference_text,
                "rights_attested": True,
            }
            profiled = await client.post("api/workspace/style-profiles", json=profile_request)
            profiled.raise_for_status()
            profile_payload = profiled.json()
            repeated = await client.post("api/workspace/style-profiles", json=profile_request)
            repeated.raise_for_status()
            if repeated.json().get("id") != profile_payload.get("id") or not repeated.json().get(
                "reused"
            ):
                raise RuntimeError("Reference profile was not reused")
            profiling_calls = len(await _model_calls(user_id))
            if profiling_calls != 0:
                raise RuntimeError("Reference profiling unexpectedly called a model")
            async with AsyncSessionLocal() as session:
                stored_profile = await session.get(StyleProfile, UUID(profile_payload["id"]))
                if stored_profile is None or reference_text[:100] in json.dumps(
                    stored_profile.features, ensure_ascii=False
                ):
                    raise RuntimeError("Raw reference text leaked into the persisted profile")

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
                    "style_profile_id": profile_payload["id"],
                    "opening_mode": "custom",
                }
            )
            created = await client.post("api/workspace/stories", json=create_payload)
            if created.is_error:
                raise RuntimeError(
                    f"Story creation failed with HTTP {created.status_code}: "
                    f"{created.text[:500]}"
                )
            workspace = created.json()
            calls_before_turn = await _model_calls(user_id)
            prior_call_ids = {call.id for call in calls_before_turn}
            idempotency_key = f"interactive-fiction-capture-{marker}"
            generated = await client.post(
                "api/chat/send",
                headers={"Idempotency-Key": idempotency_key, **headers},
                json={
                    "message": _required_string(scenario, "player_action"),
                    "story_id": workspace["story_id"],
                    "branch_id": workspace["branch_id"],
                    "branch_version": 0,
                    "control_mode": _required_string(scenario, "control_mode"),
                    "idempotency_key": idempotency_key,
                },
            )
            generated.raise_for_status()
            generated_payload = generated.json()
            generated_chapter = _required_string(generated_payload, "content")

        lifecycle_calls = await _model_calls(user_id)
        turn_calls = [call for call in lifecycle_calls if call.id not in prior_call_ids]
        if not turn_calls:
            raise RuntimeError("Narrative turn did not create an audited provider call")
        if len(lifecycle_calls) + 1 > MAX_PROVIDER_CALLS:
            raise RuntimeError("Lifecycle plus judge would exceed the capture call limit")
        author_call = turn_calls[0]
        stored_profile = None
        async with AsyncSessionLocal() as session:
            stored_profile = await session.get(StyleProfile, UUID(profile_payload["id"]))
        if stored_profile is None:
            raise RuntimeError("Style profile disappeared during capture")
        assert_non_reproducing(
            generated_chapter,
            stored_profile.content_hash,
            stored_profile.features,
        )
        prose = chapter_prose(generated_chapter)
        generated_features = public_style_features(
            analyze_style_features(
                prose,
                _required_string(scenario, "prose_language"),
                reference_content_hash(prose),
            )
        )
        judge_request = build_judge_request(
            case_payload,
            profile_payload["features"],
            generated_features,
            generated_chapter,
        )
        judged = await OpenAIAdapter(settings).generate(judge_request)
        scores = json.loads(judged.text)
        if not isinstance(scores, dict):
            raise RuntimeError("Provider judge did not return one JSON object")

        return {
            "schema_version": 1,
            "evaluation_version": _required_string(case_payload, "evaluation_version"),
            "case_sha256": canonical_sha256(case_payload),
            "evidence_kind": "provider_capture",
            "capture_method": "bounded_live_provider_end_to_end",
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "deployment_revision": args.deployment_revision,
            "capture_base_url_class": (
                "public_https" if urlsplit(args.base_url).scheme == "https" else "loopback_http"
            ),
            "reference_source_url": _required_string(reference_meta, "source_url"),
            "profile_reused": True,
            "abstract_profile": profile_payload["features"],
            "author": {"provider": author_call.provider, "model": author_call.model},
            "judge": {
                "provider": judged.provider,
                "model": judged.model,
                "prompt_version": _required_string(case_payload, "judge_prompt_version"),
                "input_tokens": judged.input_tokens,
                "output_tokens": judged.output_tokens,
                "latency_ms": judged.latency_ms,
            },
            "calls": {
                "call_limit": MAX_PROVIDER_CALLS,
                "profiling_calls": profiling_calls,
                "lifecycle_calls": len(lifecycle_calls),
                "judge_calls": 1,
                "lifecycle_routes": [
                    f"{call.provider}:{call.model}:{call.purpose}" for call in lifecycle_calls
                ],
            },
            "generated_chapter": generated_chapter,
            "generated_chapter_sha256": hashlib.sha256(generated_chapter.encode()).hexdigest(),
            "generated_features": generated_features,
            "narrative_completion": {
                "status": generated_payload.get("model_call", {}).get("completion_status"),
                "finish_reason": generated_payload.get("model_call", {}).get("finish_reason"),
                "continued_after_length_limit": generated_payload.get("model_call", {}).get(
                    "continued_after_length_limit", False
                ),
            },
            "chapter_transition": generated_payload.get("chapter_transition"),
            "scores": scores,
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
                    raise RuntimeError("Temporary capture account cleanup failed")
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one bounded end-to-end interactive-fiction sample from live providers."
        )
    )
    parser.add_argument("--case", type=Path, default=DEFAULT_ROOT / "case.json")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deployment-revision", required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--allow-http-loopback", action="store_true")
    parser.add_argument("--confirm-live-provider", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_provider:
        parser.error("--confirm-live-provider is required")
    if args.output.exists():
        parser.error("output already exists; captures are immutable")
    if not re.fullmatch(r"[0-9a-f]{40}", args.deployment_revision):
        parser.error("--deployment-revision must be one full lowercase Git SHA")
    args.base_url = _safe_base_url(args.base_url, args.allow_http_loopback)
    payload = asyncio.run(_capture(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8") as output_file:
            output_file.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
    except FileExistsError:
        parser.error("output was created during capture; refusing to overwrite it")
    print(
        "Interactive-fiction provider capture completed: "
        f"lifecycle_calls={payload['calls']['lifecycle_calls']} judge_calls=1 "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
