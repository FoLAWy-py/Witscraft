#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.evals.structured_extraction import (  # noqa: E402
    evaluate_recorded_responses,
    load_json,
    validate_route_approval,
)
from app.llm.model_registry import PURPOSE_DEFAULTS, get_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate recorded structured-extraction responses without provider traffic."
    )
    default_root = API_ROOT / "evals" / "structured_extraction" / "v1"
    parser.add_argument("--cases", type=Path, default=default_root / "cases.json")
    parser.add_argument("--responses", type=Path, default=default_root / "reference_responses.json")
    parser.add_argument("--thresholds", type=Path, default=default_root / "thresholds.json")
    parser.add_argument("--approval", type=Path, default=default_root / "route_approval.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-provider-evidence",
        action="store_true",
        help="Reject synthetic bundles when evaluating a model for route approval.",
    )
    args = parser.parse_args()

    thresholds_payload = load_json(args.thresholds)
    thresholds = thresholds_payload.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("Threshold file must contain a thresholds object")
    report = evaluate_recorded_responses(
        load_json(args.cases),
        load_json(args.responses),
        {key: float(value) for key, value in thresholds.items()},
        require_provider_evidence=args.require_provider_evidence,
    )
    default_model = PURPOSE_DEFAULTS["state_update"]
    default_option = get_model(default_model)
    if default_option is None:
        raise ValueError(f"State-update default {default_model} is not registered")
    approval_report = validate_route_approval(
        load_json(args.cases),
        {key: float(value) for key, value in thresholds.items()},
        load_json(args.approval),
        evaluation_root=args.approval.parent,
        current_provider=default_option.provider,
        current_model=default_option.model,
    )
    payload = report.as_dict()
    payload["route_approval"] = {
        "provider": default_option.provider,
        "model": default_option.model,
        "provider_capture_revalidated": approval_report is not None,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(serialized)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
