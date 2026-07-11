from __future__ import annotations

from pathlib import Path


def test_api_runbook_documents_session_auth_review_first_export_and_ownership() -> None:
    runbook = Path("docs/api-usage-runbook.md").read_text()

    for expected in (
        "There is no product API key",
        "__Host-mr_session",
        "X-CSRF-Token",
        "POST /api/discovery/jobs",
        "POST /api/me/recommendations",
        "playlist_name",
        "Idempotency-Key",
        "same Spotify account used to sign in",
        "Cross-account",
    ):
        assert expected in runbook
    assert "POST /profile/sync" not in runbook
    assert '"create_playlist": true' not in runbook


def test_architecture_and_operations_runbooks_define_file_free_product_boundary() -> None:
    architecture = Path("docs/aws-deployment-architecture-runbook.md").read_text()
    operations = Path("docs/operational-aws-runbook.md").read_text()

    for expected in (
        "Vercel",
        "API Gateway",
        "Supabase Postgres",
        "MusicBrainz",
        "ListenBrainz",
        "no CloudFront",
        "no local or S3",
        "DeployLegacyDemo=false",
    ):
        assert expected in architecture
    for expected in (
        "supabase db push",
        "OBSERVABILITY_HASH_KEY",
        "outside-the-loop-beta-admin pending",
        "outside-the-loop-beta-admin approve",
        "scripts/smoke_test_deployed_api.sh",
        "dead-letter queue",
        "rollback",
    ):
        assert expected in operations


def test_vercel_and_methodology_runbooks_cover_production_and_frozen_beta() -> None:
    vercel = Path("docs/vercel-deployment-runbook.md").read_text()
    methodology = Path("docs/recommender-methodology-runbook.md").read_text()
    spotify_policy = Path("docs/spotify-policy-assessment.md").read_text()

    for expected in (
        "PRODUCT_API_ORIGIN",
        "VITE_OAUTH_ENABLED",
        "/api/:path*",
        "Spotify redirect URI",
        "scripts/verify_vercel_deployment.sh",
        "CloudFront is not required",
    ):
        assert expected in vercel
    for expected in (
        "explicit-discovery-v1",
        "MusicBrainz",
        "ListenBrainz",
        "Spotify is not a ranking input",
        "prompt_tag_fit",
        "seed_bridge_strength",
        "discovery_value",
        "evidence_quality",
        "five testers",
        "three sessions",
        "descriptive",
    ):
        assert expected in methodology
    assert "`user-read-private` only for account identity" in spotify_policy
    assert "`user-top-read`" in spotify_policy


def test_readme_and_infra_readme_present_product_before_isolated_legacy_demo() -> None:
    readme = Path("README.md").read_text()
    infra = Path("infra/README.md").read_text()

    assert readme.index("## Product Architecture") < readme.index("## Legacy Demo")
    assert "no local files, S3 datasets, CSV, or Parquet" in readme
    assert "OutsideTheLoopApiFunction" in infra
    assert "DeployLegacyDemo=false" in infra
    assert "Product functions have no S3" in infra
