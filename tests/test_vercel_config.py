from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = REPO_ROOT / "web/vercel.mjs"
VERIFY_SCRIPT = REPO_ROOT / "scripts/verify_vercel_deployment.sh"


def test_vercel_config_uses_server_side_origin_before_spa_fallback() -> None:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            "const {config}=await import('./web/vercel.mjs'); console.log(JSON.stringify(config));",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PRODUCT_API_ORIGIN": "https://api.example.test"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["outputDirectory"] == "dist"
    assert config["rewrites"] == [
        {
            "source": "/api/:path*",
            "destination": "https://api.example.test/:path*",
        },
        {"source": "/:path*", "destination": "/index.html"},
    ]
    assert config["headers"][0]["source"] == "/api/:path*"
    assert "no-store" in config["headers"][0]["headers"][0]["value"]
    assert [rule["source"] for rule in config["headers"]] == [
        "/api/:path*",
        "/",
        "/:path*",
    ]
    assert "content-security-policy" in {
        header["key"].lower() for header in config["headers"][1]["headers"]
    }


def test_vercel_config_fails_closed_without_api_origin_and_has_no_browser_secret() -> None:
    result = subprocess.run(
        ["node", "web/vercel.mjs"],
        cwd=REPO_ROOT,
        env={key: value for key, value in os.environ.items() if key != "PRODUCT_API_ORIGIN"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    source = VERCEL_CONFIG.read_text()
    assert "PRODUCT_API_ORIGIN" in source
    assert "VITE_" not in source
    assert "SUPABASE" not in source
    assert "amazonaws.com" not in source


def test_vercel_verifier_checks_rewrite_headers_deep_links_and_build_secrets() -> None:
    source = VERIFY_SCRIPT.read_text()

    assert "/api/health" in source
    assert "/history" in source
    assert "/api/auth/spotify/start" in source
    assert "no-store" in source
    assert "content-security-policy" in source
    assert "SUPABASE_DB_URL" in source
    assert "SPOTIFY_APP_CLIENT_SECRET" in source
