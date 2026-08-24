#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.llm.deepinfra_adapter import DeepInfraAdapter  # noqa: E402
from app.llm.model_registry import get_model  # noqa: E402
from app.llm.openai_adapter import OpenAIAdapter  # noqa: E402
from app.schemas.llm import ChatMessage, LLMRequest  # noqa: E402
from app.services.state_extractor import (  # noqa: E402
    STATE_EXTRACTION_PROMPT_VERSION,
    STATE_EXTRACTION_SYSTEM_PROMPT,
)


MAX_CAPTURE_CASES = 8


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Capture input requires non-empty {key}")
    return value


def _case_set_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _request_for_case(case: dict[str, Any], provider: str, model: str) -> LLMRequest:
    prompt = {
        "previous_state": case.get("previous_state", {}),
        "previous_relationships": case.get("previous_relationships") or [],
        "perspective_character": case.get("perspective_character"),
        "user_turn": str(case.get("user_turn", "")),
        "assistant_turn": str(case.get("assistant_turn", "")),
        "chapter_context": case.get("chapter_context") or {},
    }
    return LLMRequest(
        provider=provider,
        model=model,
        purpose="state_update",
        messages=[
            ChatMessage(role="system", content=STATE_EXTRACTION_SYSTEM_PROMPT),
            ChatMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
        ],
        max_output_tokens=1800,
        temperature=0.2,
        top_p=0.85,
        response_format="json",
        stream=False,
    )


async def _capture(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    if settings.dry_run_llm:
        raise RuntimeError("Live capture refuses DRY_RUN_LLM=true")
    option = get_model(args.model)
    if option is None or option.provider != args.provider:
        raise ValueError("Provider/model pair must match the registered model catalogue")
    if args.provider == "deepinfra":
        if not settings.deepinfra_api_key:
            raise RuntimeError("DeepInfra is not configured")
        adapter = DeepInfraAdapter(settings)
    else:
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI is not configured")
        adapter = OpenAIAdapter(settings)

    cases_payload = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases_payload, dict):
        raise ValueError("Case file must contain one JSON object")
    if _required_string(cases_payload, "prompt_version") != STATE_EXTRACTION_PROMPT_VERSION:
        raise ValueError("Case prompt version does not match the application")
    expected_prompt_hash = hashlib.sha256(STATE_EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest()
    if cases_payload.get("prompt_sha256") != expected_prompt_hash:
        raise ValueError("Case prompt hash does not match the application")
    cases = cases_payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Case file must contain at least one case")
    if len(cases) > MAX_CAPTURE_CASES:
        raise ValueError(f"Live capture is hard-limited to {MAX_CAPTURE_CASES} calls")

    responses: dict[str, str] = {}
    measurements: dict[str, dict[str, int | None]] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Every case must be an object")
        case_id = _required_string(case, "id")
        response = await adapter.generate(_request_for_case(case, args.provider, args.model))
        if not response.text.strip():
            raise RuntimeError(f"Provider returned an empty response for {case_id}")
        responses[case_id] = response.text
        measurements[case_id] = {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": response.latency_ms,
        }

    measured_input = sum(item["input_tokens"] or 0 for item in measurements.values())
    measured_output = sum(item["output_tokens"] or 0 for item in measurements.values())
    measured_latency = sum(item["latency_ms"] or 0 for item in measurements.values())
    return {
        "schema_version": 1,
        "evaluation_version": _required_string(cases_payload, "evaluation_version"),
        "prompt_version": _required_string(cases_payload, "prompt_version"),
        "case_set_sha256": _case_set_hash(cases_payload),
        "evidence_kind": "provider_capture",
        "capture_method": "bounded_live_provider",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": args.provider,
        "model": args.model,
        "call_limit": MAX_CAPTURE_CASES,
        "measurements": measurements,
        "totals": {
            "calls": len(responses),
            "input_tokens": measured_input,
            "output_tokens": measured_output,
            "latency_ms": measured_latency,
        },
        "responses": responses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture one bounded structured-extraction corpus from a live provider."
    )
    default_root = API_ROOT / "evals" / "structured_extraction" / "v1"
    parser.add_argument("--cases", type=Path, default=default_root / "cases.json")
    parser.add_argument("--provider", choices=("deepinfra", "openai"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-live-provider",
        action="store_true",
        help="Required acknowledgement that the command performs billable provider calls.",
    )
    args = parser.parse_args()
    if not args.confirm_live_provider:
        parser.error("--confirm-live-provider is required")
    if args.output.exists():
        parser.error("output already exists; captures are immutable")

    payload = asyncio.run(_capture(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8") as output_file:
            output_file.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
    except FileExistsError:
        parser.error("output was created during capture; refusing to overwrite it")
    totals = payload["totals"]
    print(
        "Live provider capture completed: "
        f"calls={totals['calls']} input_tokens={totals['input_tokens']} "
        f"output_tokens={totals['output_tokens']} latency_ms={totals['latency_ms']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
