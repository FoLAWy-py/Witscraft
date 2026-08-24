from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_shell_script_is_valid_and_contains_complete_gate() -> None:
    script = ROOT / "scripts/release-preflight.sh"
    result = subprocess.run(["zsh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    content = script.read_text()
    for required in (
        "uv sync --frozen",
        "pip-audit",
        "ruff check",
        "run-backend-tests-isolated.sh",
        "npm ci",
        "npm audit",
        "npm run lint",
        "npm run typecheck",
        "npm run build:production",
        "npm run test:e2e",
        "check-production-artifacts.py",
        "create-release-manifest.py",
    ):
        assert required in content


def test_staging_release_script_is_syntactically_valid_and_isolated() -> None:
    script = ROOT / "scripts/staging-release.sh"
    result = subprocess.run(["zsh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    content = script.read_text()
    for required in (
        "pgvector/pgvector:0.8.6-pg18-bookworm",
        "witscraft-staging",
        "127.0.0.1",
        "APP_ENVIRONMENT=production",
        "uv run alembic upgrade head",
        "uv run alembic check",
        "--confirm-staging-data-reset",
        "--ca-file",
        "verify-resilience",
        "live-experience",
        "STAGING_ADDITIONAL_HOSTS",
        "allowed_hosts_json",
        "trusted_origins_json",
    ):
        assert required in content or required in (ROOT / "ops/staging/compose.yml").read_text()
    assert "myunsw.witsqua.com" not in content
    assert "deploy/nginx.remote.conf" not in content


def test_staging_nginx_normalizes_upstream_failures_without_buffering_sse() -> None:
    template = (ROOT / "ops/staging/nginx.conf.template").read_text()
    proxy = (ROOT / "ops/staging/proxy-api.conf").read_text()
    web_proxy = (ROOT / "ops/staging/proxy-web.conf").read_text()

    assert "proxy_intercept_errors on" in template
    assert "error_page 502 504 = @api_unavailable" in template
    assert "return 503" in template
    assert 'add_header Retry-After "5" always' in template
    assert "proxy_buffering off" in proxy
    assert "proxy_read_timeout 900s" in proxy
    assert "Strict-Transport-Security" in template
    assert "return 308 /witscraft/" not in template
    assert "location = /witscraft" in template
    assert "error_page 502 504 = @web_unavailable" in web_proxy


def test_slow_staging_upstream_is_loopback_only_and_bounded() -> None:
    content = (ROOT / "scripts/staging-slow-upstream.py").read_text()

    assert 'LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}' in content
    assert "server.handle_request()" in content
    assert "server.serve_forever()" not in content


def test_live_staging_experience_is_capped_sanitized_and_self_cleaning() -> None:
    content = (ROOT / "scripts/capture-staging-experience.py").read_text()

    assert "MAX_PROVIDER_CALLS = 12" in content
    assert "--confirm-live-provider" in content
    assert "Bounded capture requires one attempt and zero fallbacks" in content
    assert "delete(User).where(User.id == user_id)" in content
    assert 'ROOT / ".runtime"' in content
    assert '"content": content' not in content


def test_multiturn_provider_judge_binds_each_installment_to_its_control_mode() -> None:
    module = _load_script("capture-staging-experience.py")
    turns = [
        {
            "turn": 1,
            "control_mode": "player_action",
            "player_input": "I wait.",
            "ai_installment": "The room answers the wait.",
        },
        {
            "turn": 2,
            "control_mode": "continue",
            "player_input": "Continue.",
            "ai_installment": "The protagonist chooses a door.",
        },
    ]
    request = module._judge_request(
        settings=SimpleNamespace(default_openai_model="judge-model"),
        scenario={
            "title": "Test",
            "genre": "mystery",
            "world_name": "House",
            "premise": "A letter arrives.",
            "protagonist_name": "Eleanor",
            "protagonist_role": "guest",
            "tone": "restrained",
            "custom_prompt": "Preserve agency.",
        },
        abstract_profile={"pacing": "fast"},
        generated_features={"pacing": "moderate"},
        turns=turns,
    )
    payload = json.loads(request.messages[1].content)

    assert payload["ordered_turns"] == turns
    assert "Later player turns are new authoritative decisions" in payload["rubric"][
        "player_agency"
    ]
    assert "belongs only to profile_adherence" in payload["rubric"]["narrative_pacing"]
    assert "do not double-penalize" in request.messages[0].content
    assert module.JUDGE_PROMPT_VERSION == "staging-multiturn-experience-judge-v2"
    assert request.model == "judge-model"
    assert module._score_failures(
        {
            "profile_adherence": 65,
            "narrative_quality": 80,
            "player_agency": 90,
            "world_canon": 80,
            "narrative_pacing": 85,
            "overall": 80,
            "reasons": ["Boundaries preserved."],
        }
    ) == []


def test_backend_test_runner_creates_and_drops_an_isolated_database() -> None:
    script = ROOT / "scripts/run-backend-tests-isolated.sh"
    result = subprocess.run(["zsh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    content = script.read_text()
    for required in (
        "witscraft_preflight_test_",
        "createdb",
        "dropdb",
        "--force",
        "APP_ENVIRONMENT=test",
        'DATABASE_NAME="$TEST_DATABASE_NAME"',
        "unset WITSCRAFT_SECRETS_FILE",
        "Do not let unrelated production settings leak into pytest",
        "uv run alembic upgrade head",
    ):
        assert required in content
    assert 'TEST_DATABASE_NAME="$BASE_DATABASE_NAME"' not in content


def test_staging_observer_requires_https_and_private_runtime_output() -> None:
    module = _load_script("observe-staging.py")

    assert module._safe_https_url("https://192.0.2.10:19473/witscraft/") == (
        "https://192.0.2.10:19473/witscraft"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        module._safe_https_url("http://192.0.2.10:19473/witscraft")
    source = (ROOT / "scripts/staging-release.sh").read_text(encoding="utf-8")
    assert "observe [--minutes 30]" in source
    assert 'status >/dev/null || fail "staging must be healthy before observation"' in source
    assert 'create-release-manifest.py" --output "$RUNTIME/candidate.json"' in source


def test_slo_monitor_rejects_unsafe_targets_and_writes_private_state(tmp_path) -> None:
    module = _load_script("check-production-slos.py")

    assert module._safe_base_url("https://example.invalid/app/", False) == (
        "https://example.invalid/app"
    )
    assert module._safe_base_url("http://127.0.0.1:8000", True) == ("http://127.0.0.1:8000")
    for unsafe in (
        "http://example.invalid",
        "://".join(("https", "operator@example.invalid")),
        "https://example.invalid/?mode=probe",
    ):
        with pytest.raises(ValueError):
            module._safe_base_url(unsafe, False)

    state_file = tmp_path / "private" / "state.json"
    module._write_private_json(state_file, {"active_alerts": []})
    assert json.loads(state_file.read_text()) == {"active_alerts": []}
    assert state_file.stat().st_mode & 0o777 == 0o600
    assert state_file.parent.stat().st_mode & 0o777 == 0o700


def test_historical_secret_exception_keeps_current_file_scan() -> None:
    excluded_path = "apps/api/tests/test_release_tools.py"
    exclusions = (ROOT / ".trufflehog-exclude-paths").read_text().splitlines()
    workflow = (ROOT / ".github/workflows/security.yml").read_text()

    assert exclusions == [r"^apps/api/tests/test_release_tools\.py$"]
    assert "--exclude-paths=.trufflehog-exclude-paths" in workflow
    assert f"filesystem /tmp/{excluded_path}" in workflow
    assert "ghcr.io/trufflesecurity/trufflehog@sha256:" in workflow


def test_release_manifest_is_non_sensitive_and_bound_to_source(monkeypatch, tmp_path) -> None:
    module = _load_script("create-release-manifest.py")
    (tmp_path / "apps/api").mkdir(parents=True)
    (tmp_path / "apps/web/.next").mkdir(parents=True)
    (tmp_path / "apps/api/uv.lock").write_text("backend-lock")
    (tmp_path / "apps/web/package-lock.json").write_text("frontend-lock")
    (tmp_path / "apps/web/.next/BUILD_ID").write_text("test-build")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_git", lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(module, "_migration_heads", lambda: ["0014"])
    monkeypatch.setattr(module, "_created_at", lambda: "2026-08-17T00:00:00Z")

    manifest = module.build_manifest()

    assert manifest["application_revision"] == "a" * 40
    assert manifest["migration_heads"] == ["0014"]
    assert set(manifest["dependency_locks"]) == {
        "apps/api/uv.lock",
        "apps/web/package-lock.json",
    }
    encoded = json.dumps(manifest)
    for forbidden in ("password", "api_key", "database_host", "server_address"):
        assert forbidden not in encoded.casefold()


def test_smoke_target_rejects_credentials_and_non_loopback_http() -> None:
    module = _load_script("smoke-release.py")
    host = "example.invalid"
    credential_url = "https://" + "account" + ":" + "placeholder" + "@" + host + "/witscraft"

    assert module._safe_base_url(f"https://{host}/witscraft", False) == (
        f"https://{host}/witscraft"
    )
    assert module._safe_base_url("http://127.0.0.1:8000", True) == "http://127.0.0.1:8000"

    for invalid in (
        f"http://{host}/witscraft",
        credential_url,
        f"https://{host}/witscraft?token=placeholder",
    ):
        try:
            module._safe_base_url(invalid, False)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe smoke URL accepted: {invalid}")
