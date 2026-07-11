from __future__ import annotations

import re
import time
import uuid
from typing import Any, cast

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from music_recommender.observability import (
    ProductObserver,
    RecommendationCoverageObservation,
)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_./:{}+\-]{1,160}$")


class ProductObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, observer: ProductObserver) -> None:
        super().__init__(app)
        self.observer = observer

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _aws_request_id(request) or str(uuid.uuid4())
        request.state.observability_request_id = request_id
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency_ms = (time.perf_counter() - started) * 1_000
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            if not isinstance(route, str):
                route = "unmatched"
            status_code = response.status_code if response is not None else 500
            self.observer.api_request(
                request_id=request_id,
                method=request.method,
                route=route,
                status_code=status_code,
                latency_ms=latency_ms,
                account_id=cast(
                    str | None,
                    getattr(request.state, "observability_account_id", None),
                ),
                error_code=cast(
                    str | None,
                    getattr(request.state, "observability_error_code", None),
                ),
                recommendation=cast(
                    RecommendationCoverageObservation | None,
                    getattr(request.state, "observability_recommendation", None),
                ),
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id


def _aws_request_id(request: Request) -> str | None:
    event = request.scope.get("aws.event")
    if isinstance(event, dict):
        request_context = event.get("requestContext")
        if isinstance(request_context, dict):
            value = request_context.get("requestId")
            if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
                return value
    context = request.scope.get("aws.context")
    value = getattr(context, "aws_request_id", None)
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return None
