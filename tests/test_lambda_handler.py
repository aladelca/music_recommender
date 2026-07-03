from __future__ import annotations

import json
from typing import Any, cast

import pytest

from music_recommender.api.lambda_handler import handler


class LambdaContext:
    function_name = "music-recommender-demo"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:music-recommender-demo"
    aws_request_id = "request-id"

    @staticmethod
    def get_remaining_time_in_millis() -> int:
        return 30_000


def test_lambda_handler_serves_health_without_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "spotify-client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "spotify-secret")

    response = handler(_http_api_event("GET", "/health"), cast(Any, LambdaContext()))

    assert response["statusCode"] == 200
    body = json.loads(str(response["body"]))
    assert body["status"] == "ok"
    assert body["config"]["spotify_client_id_present"] is True
    assert "spotify-secret" not in response["body"]


def _http_api_event(method: str, path: str) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {
            "accept": "application/json",
            "host": "api.example.com",
            "x-forwarded-port": "443",
            "x-forwarded-proto": "https",
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "api-id",
            "domainName": "api.example.com",
            "domainPrefix": "api",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "request-id",
            "routeKey": f"{method} {path}",
            "stage": "$default",
            "time": "03/Jul/2026:22:00:00 +0000",
            "timeEpoch": 1_783_115_200_000,
        },
        "isBase64Encoded": False,
    }
