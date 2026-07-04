from __future__ import annotations

from typing import Any

from music_recommender.api_cli import main


def test_api_cli_runs_uvicorn_app_with_configured_host_and_port() -> None:
    calls: list[dict[str, Any]] = []

    def runner(app: str, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    exit_code = main(["--host", "0.0.0.0", "--port", "9000", "--reload"], runner=runner)

    assert exit_code == 0
    assert calls == [
        {
            "app": "music_recommender.api.app:app",
            "host": "0.0.0.0",
            "port": 9000,
            "reload": True,
        }
    ]
