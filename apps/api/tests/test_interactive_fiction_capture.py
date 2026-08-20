import runpy
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = REPOSITORY_ROOT / "scripts" / "capture-interactive-fiction.py"


def test_live_interactive_fiction_capture_has_a_hard_call_cap_and_safe_url_boundary() -> None:
    namespace = runpy.run_path(str(CAPTURE_SCRIPT), run_name="interactive_capture_test")

    assert namespace["MAX_PROVIDER_CALLS"] == 8
    assert namespace["_safe_base_url"]("https://example.com/witscraft", False) == (
        "https://example.com/witscraft"
    )
    assert namespace["_safe_base_url"]("http://127.0.0.1:8000", True) == ("http://127.0.0.1:8000")
