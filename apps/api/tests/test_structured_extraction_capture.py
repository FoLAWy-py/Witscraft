import json
import runpy
from pathlib import Path

from app.services.state_extractor import STATE_EXTRACTION_SYSTEM_PROMPT


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = REPOSITORY_ROOT / "scripts" / "capture-structured-extraction.py"
EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals" / "structured_extraction" / "v1"


def test_live_capture_is_bounded_and_matches_the_versioned_prompt_contract() -> None:
    namespace = runpy.run_path(str(CAPTURE_SCRIPT), run_name="structured_capture_test")
    cases = json.loads((EVAL_ROOT / "cases.json").read_text(encoding="utf-8"))
    reference = json.loads(
        (EVAL_ROOT / "reference_responses.json").read_text(encoding="utf-8")
    )

    assert len(cases["cases"]) == namespace["MAX_CAPTURE_CASES"] == 8
    assert namespace["_case_set_hash"](cases) == reference["case_set_sha256"]

    request = namespace["_request_for_case"](
        cases["cases"][0], "deepinfra", "Qwen/Qwen3-Max"
    )
    assert request.purpose == "state_update"
    assert request.response_format == "json"
    assert request.max_output_tokens == 1800
    assert request.temperature == 0.2
    assert request.top_p == 0.85
    assert request.messages[0].content == STATE_EXTRACTION_SYSTEM_PROMPT
    prompt = json.loads(request.messages[1].content)
    assert prompt["previous_state"] == cases["cases"][0]["previous_state"]
    assert prompt["user_turn"] == cases["cases"][0]["user_turn"]
    assert prompt["assistant_turn"] == cases["cases"][0]["assistant_turn"]
