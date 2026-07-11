from __future__ import annotations

from pathlib import Path


def test_ci_runs_python_supabase_frontend_browser_package_and_secret_gates() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()

    for expected in (
        "uv run ruff format --check",
        "uv run mypy",
        "uv run pytest -q",
        "supabase db reset",
        "supabase db lint --local",
        "supabase test db",
        "npm audit --audit-level=high",
        "npm run test:e2e",
        "sam validate --lint",
        "scripts/prune_lambda_artifacts.sh",
        "*.parquet",
        "*.csv",
        "gitleaks/gitleaks-action@v2",
    ):
        assert expected in workflow


def test_aws_deployment_uses_oidc_manual_approval_and_product_only_stack() -> None:
    workflow = Path(".github/workflows/deploy-aws.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "id-token: write" in workflow
    assert "environment: production" in workflow
    assert "aws-actions/configure-aws-credentials@v6" in workflow
    assert "role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}" in workflow
    assert 'DEPLOY_LEGACY_DEMO: "false"' in workflow
    assert "AWS_ACCESS_KEY_ID" not in workflow
    assert "AWS_SECRET_ACCESS_KEY" not in workflow
