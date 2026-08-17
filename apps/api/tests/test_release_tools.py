from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


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
        "pytest -q",
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


def test_release_manifest_is_non_sensitive_and_bound_to_source(monkeypatch, tmp_path) -> None:
    module = _load_script("create-release-manifest.py")
    (tmp_path / "apps/api").mkdir(parents=True)
    (tmp_path / "apps/web/.next").mkdir(parents=True)
    (tmp_path / "apps/api/uv.lock").write_text("backend-lock")
    (tmp_path / "apps/web/package-lock.json").write_text("frontend-lock")
    (tmp_path / "apps/web/.next/BUILD_ID").write_text("test-build")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_git", lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(module, "_migration_heads", lambda: ["0013"])
    monkeypatch.setattr(module, "_created_at", lambda: "2026-08-17T00:00:00Z")

    manifest = module.build_manifest()

    assert manifest["application_revision"] == "a" * 40
    assert manifest["migration_heads"] == ["0013"]
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
