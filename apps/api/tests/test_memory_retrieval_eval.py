import json
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "memory_retrieval" / "v1"


def test_memory_retrieval_corpus_and_threshold_contract() -> None:
    cases = json.loads((EVAL_DIR / "cases.json").read_text())
    thresholds = json.loads((EVAL_DIR / "thresholds.json").read_text())

    assert len(cases) >= 8
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["query"].strip() for case in cases)
    assert all(case["relevant"] != case["trap"] for case in cases)
    assert thresholds["candidate_rows"] >= 10_000
    assert thresholds["iterations"] >= len(cases) * 3
    assert thresholds["min_recall_at_8"] >= 0.85
    assert thresholds["max_error_recall_rate"] <= 0.05
    assert thresholds["max_p95_latency_ms"] <= 500


def test_memory_retrieval_corpus_contains_no_live_identifiers() -> None:
    serialized = (EVAL_DIR / "cases.json").read_text().lower()

    assert "@" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert "api_key" not in serialized
