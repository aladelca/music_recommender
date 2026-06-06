from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ApiError(Exception):
    status_code: int
    url: str
    message: str
    payload: Any | None = None

    def __str__(self) -> str:
        return f"{self.status_code} {self.url}: {self.message}"


class ApiHttpClient:
    def __init__(
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_retries = max_retries
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(
        self,
        path: str,
        *,
        expected_statuses: Iterable[int] = (200,),
        **kwargs: Any,
    ) -> httpx.Response:
        return self.request("GET", path, expected_statuses=expected_statuses, **kwargs)

    def post(
        self,
        path: str,
        *,
        expected_statuses: Iterable[int] = (200,),
        **kwargs: Any,
    ) -> httpx.Response:
        return self.request("POST", path, expected_statuses=expected_statuses, **kwargs)

    def request(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: Iterable[int] = (200,),
        **kwargs: Any,
    ) -> httpx.Response:
        expected = set(expected_statuses)
        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = self._client.request(method, path, **kwargs)
            last_response = response
            if response.status_code in expected:
                return response
            if self._should_retry(response.status_code) and attempt < self.max_retries:
                self._sleep(self._retry_delay(response, attempt))
                continue
            raise self._error_from_response(response)

        if last_response is None:
            raise ApiError(status_code=0, url=path, message="No response received")
        raise self._error_from_response(last_response)

    @staticmethod
    def _should_retry(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return min(2.0**attempt, 30.0)

    @staticmethod
    def _error_from_response(response: httpx.Response) -> ApiError:
        try:
            payload: Any | None = response.json()
        except ValueError:
            payload = response.text
        return ApiError(
            status_code=response.status_code,
            url=str(response.url),
            message=response.reason_phrase,
            payload=payload,
        )
