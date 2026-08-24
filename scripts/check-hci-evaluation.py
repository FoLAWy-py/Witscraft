#!/usr/bin/env python3
"""Validate versioned HCI evidence without pretending expert review is user research."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "hci-review-2026-08-24.json"


def weighted_score(dimensions: list[dict], field: str) -> float:
    return round(sum(item["weight"] * item[field] / 4 for item in dimensions), 2)


def main() -> None:
    payload = json.loads(EVIDENCE.read_text())
    dimensions = payload["dimensions"]
    assert payload["schema_version"] == "hci-review-v1"
    assert sum(item["weight"] for item in dimensions) == 100
    assert len({item["id"] for item in dimensions}) == len(dimensions)
    for item in dimensions:
        assert 0 <= item["baseline"] <= 4
        assert 0 <= item["retest"] <= 4

    baseline = weighted_score(dimensions, "baseline")
    retest = weighted_score(dimensions, "retest")
    assert baseline == payload["expected_scores"]["baseline"]
    assert retest == payload["expected_scores"]["retest"]
    assert retest >= payload["release_gate"]["minimum_weighted_score"]
    assert all(task["passed"] for task in payload["critical_tasks"])
    assert all(
        item["retest"] >= payload["release_gate"]["minimum_core_dimension_rating"]
        for item in dimensions
        if item["core"]
    )
    assert not any(
        issue["severity"] in payload["release_gate"]["prohibited_severities"]
        for issue in payload["open_issues"]
    )
    assert payload["participant_validation"]["status"] == "pending"
    assert payload["participant_validation"]["participants"] == 0
    print(f"HCI expert gate passed: {retest:.2f}/100 (baseline {baseline:.2f}/100)")
    print("Participant validation: pending (no participant results inferred)")


if __name__ == "__main__":
    main()
