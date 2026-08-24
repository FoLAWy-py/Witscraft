import runpy
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = REPOSITORY_ROOT / "scripts" / "capture-interactive-fiction.py"


def test_live_interactive_fiction_capture_has_a_hard_call_cap_and_safe_url_boundary() -> None:
    namespace = runpy.run_path(str(CAPTURE_SCRIPT), run_name="interactive_capture_test")

    assert namespace["MAX_PROVIDER_CALLS"] == 8
    https_base = namespace["_safe_base_url"]("https://example.com/witscraft", False)
    loopback_base = namespace["_safe_base_url"]("http://127.0.0.1:8000", True)

    assert https_base == "https://example.com/witscraft/"
    assert loopback_base == "http://127.0.0.1:8000/"

    httpx = namespace["httpx"]
    with httpx.Client(base_url=https_base) as client:
        assert str(client.base_url.join("api/auth/login")) == (
            "https://example.com/witscraft/api/auth/login"
        )


def test_live_capture_supports_a_private_staging_ca_without_disabling_tls() -> None:
    source = CAPTURE_SCRIPT.read_text(encoding="utf-8")

    assert 'parser.add_argument(\n        "--ca-file"' in source
    assert "ssl.create_default_context(cafile=args.ca_file)" in source
    assert "verify=args.tls_context" in source
    assert "verify=False" not in source
