from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

ServiceName = Literal["product-api", "discovery-worker", "cleanup"]
SourceStatusClass = Literal["success", "degraded", "transient_failure", "permanent_failure"]
MetricUnit = Literal["Count", "Milliseconds", "Percent"]
EventEmitter = Callable[[dict[str, Any]], None]

_LOGGER = logging.getLogger("music_recommender.product")
_LOGGER.setLevel(logging.INFO)
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_./:{}+\-]{1,160}$")
_METRIC_NAMESPACE = "OutsideTheLoop/Product"


@dataclass(frozen=True)
class RecommendationCoverageObservation:
    status: Literal["ready", "degraded", "insufficient"]
    candidate_count: int
    mapped_count: int
    evidence_count: int
    evidence_coverage: float

    def __post_init__(self) -> None:
        if self.candidate_count < 0 or self.mapped_count < 0 or self.evidence_count < 0:
            raise ValueError("Recommendation coverage counts must not be negative.")
        if self.mapped_count > self.candidate_count or self.evidence_count > self.mapped_count:
            raise ValueError("Recommendation coverage counts are inconsistent.")
        if not 0.0 <= self.evidence_coverage <= 1.0:
            raise ValueError("Evidence coverage must be between zero and one.")


@dataclass(frozen=True)
class _Metric:
    name: str
    value: int | float
    unit: MetricUnit


class ProductObserver:
    def __init__(
        self,
        *,
        service: ServiceName,
        hash_key: str | None = None,
        emitter: EventEmitter | None = None,
        epoch_milliseconds: Callable[[], int] | None = None,
    ) -> None:
        if hash_key is not None and (len(hash_key) < 32 or len(hash_key) > 512):
            raise ValueError(
                "The observability hash key must contain between 32 and 512 characters."
            )
        self.service = service
        self._hash_key = hash_key.encode("utf-8") if hash_key is not None else None
        self._emitter = emitter or self._log_event
        self._epoch_milliseconds = epoch_milliseconds or (lambda: time.time_ns() // 1_000_000)

    def api_request(
        self,
        *,
        request_id: str,
        method: str,
        route: str,
        status_code: int,
        latency_ms: float,
        account_id: str | None,
        error_code: str | None,
        recommendation: RecommendationCoverageObservation | None,
    ) -> None:
        safe_status = status_code if 100 <= status_code <= 599 else 500
        fields: dict[str, Any] = {
            "request_id": _safe_label(request_id, fallback="generated"),
            "method": _safe_label(method.upper(), fallback="UNKNOWN"),
            "route": _safe_label(route, fallback="unmatched"),
            "status_code": safe_status,
            "status_class": f"{safe_status // 100}xx",
            "latency_ms": _non_negative_number(latency_ms),
        }
        metrics = [
            _Metric("RequestCount", 1, "Count"),
            _Metric("RequestLatencyMs", fields["latency_ms"], "Milliseconds"),
        ]
        if safe_status >= 500:
            metrics.append(_Metric("ApiErrorCount", 1, "Count"))
        if route == "/ready" and safe_status >= 500:
            metrics.append(_Metric("DatabaseFailureCount", 1, "Count"))
        if route == "/me/recommendations/{session_id}/playlist":
            metric_name = (
                "PlaylistExportSuccessCount" if safe_status < 400 else "PlaylistExportFailureCount"
            )
            metrics.append(_Metric(metric_name, 1, "Count"))
        if error_code is not None:
            fields["error_code"] = _safe_label(error_code, fallback="internal_error")
            if error_code == "spotify_reconnect_required":
                metrics.append(_Metric("SpotifyReconnectCount", 1, "Count"))
            if error_code in {
                "discovery_source_unavailable",
                "spotify_temporarily_unavailable",
                "spotify_invalid_response",
            }:
                metrics.append(_Metric("SourceFailureCount", 1, "Count"))
        if account_id is not None:
            fields["user_correlation"] = self.user_correlation(account_id)
        if recommendation is not None:
            source_coverage = (
                recommendation.mapped_count / recommendation.candidate_count
                if recommendation.candidate_count
                else 0.0
            )
            fields.update(
                {
                    "recommendation_status": recommendation.status,
                    "candidate_count": recommendation.candidate_count,
                    "mapped_count": recommendation.mapped_count,
                    "evidence_count": recommendation.evidence_count,
                }
            )
            metrics.extend(
                (
                    _Metric(
                        "RecommendationSourceCoveragePercent",
                        round(source_coverage * 100, 2),
                        "Percent",
                    ),
                    _Metric(
                        "RecommendationEvidenceCoveragePercent",
                        round(recommendation.evidence_coverage * 100, 2),
                        "Percent",
                    ),
                )
            )
        self._emit("api_request", fields=fields, metrics=metrics)

    def cache_lookup(
        self,
        *,
        source: Literal["musicbrainz", "listenbrainz", "spotify_mapping"],
        hit: bool,
        cache_status: Literal["fresh", "negative", "error", "missing"],
    ) -> None:
        metric = "CacheHitCount" if hit else "CacheMissCount"
        self._emit(
            "cache_lookup",
            fields={"source": source, "cache_status": cache_status},
            metrics=[_Metric(metric, 1, "Count"), _Metric("CacheLookupCount", 1, "Count")],
        )

    def source_request(
        self,
        *,
        source: Literal["musicbrainz", "listenbrainz", "spotify"],
        status_class: SourceStatusClass,
    ) -> None:
        metrics = [_Metric("SourceRequestCount", 1, "Count")]
        if status_class in {"transient_failure", "permanent_failure"}:
            metrics.append(_Metric("SourceFailureCount", 1, "Count"))
        self._emit(
            "source_request",
            fields={"source": source, "source_status_class": status_class},
            metrics=metrics,
        )

    def discovery_message(
        self,
        *,
        request_id: str,
        account_id: str,
        job_status: str,
        source_status_class: SourceStatusClass,
        queue_age_ms: float,
        latency_ms: float,
        succeeded: bool,
    ) -> None:
        metrics = [
            _Metric("DiscoveryMessageCount", 1, "Count"),
            _Metric("QueueAgeMs", _non_negative_number(queue_age_ms), "Milliseconds"),
            _Metric("DiscoveryLatencyMs", _non_negative_number(latency_ms), "Milliseconds"),
        ]
        if not succeeded:
            metrics.append(_Metric("DiscoveryFailureCount", 1, "Count"))
        self._emit(
            "discovery_message",
            fields={
                "request_id": _safe_label(request_id, fallback="unknown"),
                "user_correlation": self.user_correlation(account_id),
                "job_status": _safe_label(job_status, fallback="unknown"),
                "source_status_class": source_status_class,
            },
            metrics=metrics,
        )

    def playlist_outcome(self, *, succeeded: bool) -> None:
        metric = "PlaylistExportSuccessCount" if succeeded else "PlaylistExportFailureCount"
        self._emit(
            "playlist_outcome",
            fields={"succeeded": succeeded},
            metrics=[_Metric(metric, 1, "Count")],
        )

    def spotify_reconnect(self) -> None:
        self._emit(
            "spotify_reconnect",
            fields={},
            metrics=[_Metric("SpotifyReconnectCount", 1, "Count")],
        )

    def cleanup(self, *, deleted_count: int, latency_ms: float, succeeded: bool) -> None:
        safe_deleted = max(deleted_count, 0)
        metrics = [
            _Metric("CleanupRunCount", 1, "Count"),
            _Metric("CleanupDeletedCount", safe_deleted, "Count"),
            _Metric("CleanupLatencyMs", _non_negative_number(latency_ms), "Milliseconds"),
        ]
        if not succeeded:
            metrics.append(_Metric("DatabaseFailureCount", 1, "Count"))
        self._emit(
            "cleanup",
            fields={"succeeded": succeeded},
            metrics=metrics,
        )

    def user_correlation(self, account_id: str) -> str:
        if self._hash_key is None:
            raise RuntimeError("An observability hash key is required for user correlation.")
        normalized = account_id.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError("The internal account identifier is invalid.")
        return hmac.new(self._hash_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def _emit(
        self,
        event: str,
        *,
        fields: dict[str, Any],
        metrics: list[_Metric],
    ) -> None:
        payload: dict[str, Any] = {
            "_aws": {
                "Timestamp": self._epoch_milliseconds(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _METRIC_NAMESPACE,
                        "Dimensions": [["Service"]],
                        "Metrics": [
                            {"Name": metric.name, "Unit": metric.unit} for metric in metrics
                        ],
                    }
                ],
            },
            "Service": self.service,
            "event": event,
            **fields,
        }
        payload.update({metric.name: metric.value for metric in metrics})
        try:
            self._emitter(payload)
        except Exception:
            _LOGGER.warning('{"event":"observability_emit_failed"}')

    @staticmethod
    def _log_event(payload: dict[str, Any]) -> None:
        _LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def mark_request_account(request: Any, *, account_id: str) -> None:
    request.state.observability_account_id = account_id


def mark_request_error(request: Any, *, error_code: str) -> None:
    request.state.observability_error_code = _safe_label(error_code, fallback="internal_error")


def mark_recommendation_coverage(
    request: Any,
    observation: RecommendationCoverageObservation,
) -> None:
    request.state.observability_recommendation = observation


def _safe_label(value: str, *, fallback: str) -> str:
    return value if _SAFE_LABEL.fullmatch(value) else fallback


def _non_negative_number(value: int | float) -> float:
    if not isinstance(value, (int, float)) or value < 0:
        return 0.0
    return round(float(value), 3)
