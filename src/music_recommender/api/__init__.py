"""Backend API entry points for the music recommender demo."""

from typing import Any

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from music_recommender.api.app import app

        return app
    if name == "create_app":
        from music_recommender.api.app import create_app

        return create_app
    raise AttributeError(name)
