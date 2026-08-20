#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
DEFAULT_ROOT = API_ROOT / "evals" / "interactive_fiction" / "v1"
sys.path.insert(0, str(API_ROOT))

from app.evals.interactive_fiction import evaluate_provider_capture  # noqa: E402


def _load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a reviewed real-provider interactive-fiction capture without provider traffic."
        )
    )
    parser.add_argument("--case", type=Path, default=DEFAULT_ROOT / "case.json")
    parser.add_argument("--capture", type=Path, default=DEFAULT_ROOT / "provider-capture-v3.json")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_ROOT / "thresholds.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    case_payload = _load_object(args.case)
    reference = case_payload.get("reference")
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise ValueError("Case reference.path must be a string")
    reference_path = (args.case.parent / reference["path"]).resolve()
    if not reference_path.is_relative_to(args.case.parent.resolve()):
        raise ValueError("Reference path must remain inside the evaluation directory")
    thresholds_payload = _load_object(args.thresholds)
    thresholds = thresholds_payload.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("Threshold bundle must contain a thresholds object")
    report = evaluate_provider_capture(
        case_payload,
        reference_path.read_text(encoding="utf-8"),
        _load_object(args.capture),
        {key: float(value) for key, value in thresholds.items()},
    )
    serialized = json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
