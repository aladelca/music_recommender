from __future__ import annotations

from typing import Any

from fastapi import Request


def get_api_service(request: Request) -> Any:
    return request.app.state.api_service
