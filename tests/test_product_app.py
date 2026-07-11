from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from types import SimpleNamespace

from fastapi.testclient import TestClient

from music_recommender.api.product_app import create_product_app
from music_recommender.observability import ProductObserver


def test_product_app_exposes_only_product_routes_and_shallow_health() -> None:
    observed: list[dict[str, object]] = []
    runtime = SimpleNamespace(
        auth_service=object(),
        session_service=object(),
        csrf_protection=object(),
        database=object(),
        seed_service=object(),
        discovery_job_service=object(),
        recommendation_service=object(),
        playlist_export_service=object(),
        feedback_evaluation_service=object(),
        account_service=object(),
        observer=ProductObserver(service="product-api", emitter=observed.append),
        ready=lambda: True,
    )
    app = create_product_app(runtime=runtime)
    client = TestClient(app)

    health = client.get("/health")
    assert health.json() == {"status": "ok", "version": "0.1.0"}
    assert health.headers["x-request-id"]
    assert client.get("/ready").json() == {"status": "ready"}
    route_paths = _route_paths(app.routes)
    assert "/auth/spotify/start" in route_paths
    assert "/me/recommendations" in route_paths
    assert "/discovery/jobs" in route_paths
    assert "/recommendations" not in route_paths
    assert "/playlists" not in route_paths
    assert "/feedback" not in route_paths
    assert "/profile" not in route_paths
    assert "/openapi.json" not in route_paths
    assert observed[0]["route"] == "/health"


def test_product_app_import_uses_only_product_runtime_dependencies() -> None:
    code = """
import builtins
real_import = builtins.__import__
def product_import(name, globals=None, locals=None, fromlist=(), level=0):
    blocked = ('agents', 'yaml')
    if any(name == package or name.startswith(f'{package}.') for package in blocked):
        raise ModuleNotFoundError(f"{name} is unavailable in the product runtime")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = product_import
import music_recommender.api.product_app
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _route_paths(routes: Sequence[object]) -> set[str]:
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        nested = getattr(route, "routes", None)
        if isinstance(nested, list):
            paths.update(_route_paths(nested))
        original_router = getattr(route, "original_router", None)
        original_routes = getattr(original_router, "routes", None)
        if isinstance(original_routes, list):
            paths.update(_route_paths(original_routes))
    return paths
