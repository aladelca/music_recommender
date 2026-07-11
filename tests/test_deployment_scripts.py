from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_SCRIPT = REPO_ROOT / "scripts/sync_runtime_secret.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts/deploy_api_sam.sh"
SMOKE_SCRIPT = REPO_ROOT / "scripts/smoke_test_deployed_api.sh"
PREPARE_BUILD_SCRIPT = REPO_ROOT / "scripts/prepare_lambda_build.sh"
PRUNE_ARTIFACTS_SCRIPT = REPO_ROOT / "scripts/prune_lambda_artifacts.sh"


def test_runtime_secret_script_fails_before_aws_when_env_is_incomplete(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "aws-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "aws",
        f"#!/usr/bin/env bash\ntouch {marker!s}\nexit 99\n",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("SPOTIFY_APP_CLIENT_ID=client-only\n")

    result = _run_secret_script(fake_bin=fake_bin, env_file=env_file)

    assert result.returncode != 0
    assert "Missing required runtime secret values" in result.stderr
    assert not marker.exists()


def test_runtime_secret_script_writes_product_values_and_redacts_them(tmp_path: Path) -> None:
    capture_file = tmp_path / "secret.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "aws",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "secretsmanager describe-secret") exit 0 ;;
  "secretsmanager get-secret-value")
    printf '%s' '{"RECOMMENDER_API_KEY":"existing-api-key-that-is-long-enough-123456"'
    printf '%s\\n' ',"old":"ignored"}'
    ;;
  "secretsmanager put-secret-value")
    cat > "$CAPTURE_FILE"
    printf '%s\\n' '{"VersionId":"redacted-version"}'
    ;;
  *) exit 98 ;;
esac
""",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SPOTIFY_APP_CLIENT_ID=dummy-client-id\n"
        "SPOTIFY_APP_CLIENT_SECRET=dummy-client-secret\n"
        "SUPABASE_DB_URL=postgresql://example.invalid/product?sslmode=require\n"
        "OBSERVABILITY_HASH_KEY=dummy-observability-key-that-is-long-enough\n"
    )

    result = _run_secret_script(
        fake_bin=fake_bin,
        env_file=env_file,
        extra_env={"CAPTURE_FILE": str(capture_file)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(capture_file.read_text())
    assert payload == {
        "SPOTIFY_APP_CLIENT_ID": "dummy-client-id",
        "SPOTIFY_APP_CLIENT_SECRET": "dummy-client-secret",
        "SUPABASE_DB_URL": "postgresql://example.invalid/product?sslmode=require",
        "OBSERVABILITY_HASH_KEY": "dummy-observability-key-that-is-long-enough",
    }
    combined_output = result.stdout + result.stderr
    for secret_value in payload.values():
        assert secret_value not in combined_output


def test_runtime_secret_script_does_not_put_secret_json_in_process_arguments() -> None:
    script = SECRET_SCRIPT.read_text()

    assert "set -euo pipefail" in script
    assert "set -x" not in script
    assert "--secret-string file:///dev/stdin" in script
    assert '--secret-string "$secret_json"' not in script


def test_deploy_script_checks_product_database_and_packages_before_sam_deploy() -> None:
    script = DEPLOY_SCRIPT.read_text()

    assert "music_recommender.deployment_preflight" in script
    assert "SUPABASE_DB_URL" in script
    assert "OBSERVABILITY_HASH_KEY" in script
    assert "ProductRuntimeSecretName=" in script
    assert "AppBaseUrl=" in script
    assert "MusicBrainzContactEmail=" in script
    assert 'if [[ "$DEPLOY_LEGACY_DEMO_VALUE" == "true" ]]' in script
    assert "check-s3-data" in script
    assert "sam validate --lint" in script
    assert "--no-confirm-changeset" in script
    assert "--no-fail-on-empty-changeset" in script
    assert "--resolve-s3" not in script
    assert "--s3-bucket" in script
    assert "--role-arn" in script
    assert "bash scripts/prepare_lambda_build.sh" in script
    assert "bash scripts/prune_lambda_artifacts.sh" in script
    assert "MAX_LAMBDA_UNZIPPED_KB=262144" in script
    assert "MAX_PRODUCT_UNZIPPED_KB=131072" in script
    assert "MusicRecommenderApiFunction" in script
    assert "MusicRecommenderProfileSyncFunction" in script
    assert "OutsideTheLoopApiFunction" in script
    assert "OutsideTheLoopDiscoveryWorkerFunction" in script
    assert "OutsideTheLoopCleanupFunction" in script
    assert "parameter_overrides=(" in script
    assert '"DeployLegacyDemo=${DEPLOY_LEGACY_DEMO_VALUE}"' in script
    assert '"EnableReservedConcurrency=${ENABLE_RESERVED_CONCURRENCY_VALUE}"' in script
    assert "set -x" not in script


def test_smoke_script_covers_product_health_auth_and_queue_without_secrets() -> None:
    script = SMOKE_SCRIPT.read_text()

    assert "aws cloudformation describe-stacks" in script
    assert "aws secretsmanager get-secret-value" not in script
    assert "RECOMMENDER_API_KEY" not in script
    for path in (
        "/health",
        "/ready",
        "/auth/me",
        "/auth/spotify/start",
        "/me/seeds",
        "/recommendations",
    ):
        assert path in script
    assert 'assert_status "401"' in script
    assert 'assert_status "404"' in script
    assert "accounts.spotify.com/authorize" in script
    assert "ApproximateNumberOfMessages" in script
    assert "create_playlist" not in script


def test_lambda_build_context_contains_only_source_and_scoped_requirements(
    tmp_path: Path,
) -> None:
    build_root = tmp_path / "lambda-build"
    result = subprocess.run(
        ["bash", str(PREPARE_BUILD_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "LAMBDA_BUILD_ROOT": str(build_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    api_root = build_root / "api"
    scheduler_root = build_root / "profile-sync"
    product_root = build_root / "product-api"
    worker_root = build_root / "discovery-worker"
    cleanup_root = build_root / "cleanup"
    assert (api_root / "src/music_recommender/api/lambda_handler.py").is_file()
    assert (scheduler_root / "src/music_recommender/api/scheduled_profile_handler.py").is_file()
    assert (product_root / "src/music_recommender/api/product_lambda_handler.py").is_file()
    assert (worker_root / "src/music_recommender/api/discovery_worker_handler.py").is_file()
    assert (cleanup_root / "src/music_recommender/api/cleanup_handler.py").is_file()
    assert not (api_root / "data").exists()
    assert not (scheduler_root / "data").exists()
    for context_root in (api_root, scheduler_root, product_root, worker_root, cleanup_root):
        assert list(context_root.rglob("*.parquet")) == []
        assert list(context_root.rglob("*.csv")) == []

    api_requirements = (api_root / "requirements.txt").read_text().lower()
    scheduler_requirements = (scheduler_root / "requirements.txt").read_text().lower()
    assert "pyarrow==" in api_requirements
    assert "openai-agents==" in api_requirements
    assert "openai==2.44.0" in api_requirements
    assert "pyyaml==" in api_requirements
    assert "boto3" not in api_requirements
    assert "botocore" not in api_requirements
    assert "pyarrow" not in scheduler_requirements
    assert "openai" not in scheduler_requirements
    assert "fastapi" not in scheduler_requirements
    product_requirements = (product_root / "requirements.txt").read_text().lower()
    worker_requirements = (worker_root / "requirements.txt").read_text().lower()
    cleanup_requirements = (cleanup_root / "requirements.txt").read_text().lower()
    assert "fastapi==" in product_requirements
    assert "mangum==" in product_requirements
    assert "psycopg" in product_requirements
    for forbidden_dependency in ("pyarrow", "openai", "pandas", "numpy"):
        assert forbidden_dependency not in product_requirements
        assert forbidden_dependency not in worker_requirements
        assert forbidden_dependency not in cleanup_requirements


def test_lambda_build_script_rejects_parquet_and_csv_files_explicitly() -> None:
    script = PREPARE_BUILD_SCRIPT.read_text()

    assert "-iname '*.parquet'" in script
    assert "-iname '*.csv'" in script
    assert "Refusing to package forbidden deployment data file" in script


def test_lambda_artifact_pruning_removes_pyarrow_test_data(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    pyarrow_tests = artifact_root / "MusicRecommenderApiFunction/pyarrow/tests/data"
    pyarrow_tests.mkdir(parents=True)
    (pyarrow_tests / "fixture.parquet").write_text("fixture")
    source_file = artifact_root / "MusicRecommenderApiFunction/src/app.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("value = 1\n")
    _create_other_artifact_directories(artifact_root)

    result = subprocess.run(
        ["bash", str(PRUNE_ARTIFACTS_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "LAMBDA_ARTIFACT_ROOT": str(artifact_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (artifact_root / "MusicRecommenderApiFunction/pyarrow/tests").exists()
    assert source_file.is_file()


def test_lambda_artifact_pruning_rejects_unexpected_csv(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    api_root = artifact_root / "MusicRecommenderApiFunction"
    api_root.mkdir(parents=True)
    (api_root / "unexpected.csv").write_text("must-not-deploy")
    _create_other_artifact_directories(artifact_root)

    result = subprocess.run(
        ["bash", str(PRUNE_ARTIFACTS_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "LAMBDA_ARTIFACT_ROOT": str(artifact_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "forbidden Parquet/CSV file" in result.stderr


def _run_secret_script(
    *,
    fake_bin: Path,
    env_file: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "OPENAI_API_KEY": "",
        "RECOMMENDER_API_KEY": "",
        "SPOTIFY_APP_CLIENT_ID": "",
        "SPOTIFY_APP_CLIENT_SECRET": "",
        "SPOTIFY_USER_REFRESH_TOKEN": "",
        "SUPABASE_DB_URL": "",
        "OBSERVABILITY_HASH_KEY": "",
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "ENV_FILE": str(env_file),
        "AWS_REGION_VALUE": "us-east-1",
        "RUNTIME_SECRET_NAME": "music-recommender/test/runtime",
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", str(SECRET_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _create_other_artifact_directories(artifact_root: Path) -> None:
    for name in (
        "MusicRecommenderProfileSyncFunction",
        "OutsideTheLoopApiFunction",
        "OutsideTheLoopDiscoveryWorkerFunction",
        "OutsideTheLoopCleanupFunction",
    ):
        (artifact_root / name).mkdir(parents=True, exist_ok=True)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)
