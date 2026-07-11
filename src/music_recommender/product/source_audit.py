from __future__ import annotations

import math
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from music_recommender.models import JsonDict


class SourceAuditDatabase(Protocol):
    def system_transaction(self) -> AbstractContextManager[Any]: ...


@dataclass(frozen=True)
class SourceInventoryAudit:
    status: str
    fresh_candidate_count: int
    fresh_spotify_mapping_count: int
    evidenced_mapping_count: int
    stale_candidate_count: int
    evidence_coverage: float
    limitations: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return {
            "status": self.status,
            "fresh_candidate_count": self.fresh_candidate_count,
            "fresh_spotify_mapping_count": self.fresh_spotify_mapping_count,
            "evidenced_mapping_count": self.evidenced_mapping_count,
            "stale_candidate_count": self.stale_candidate_count,
            "evidence_coverage": self.evidence_coverage,
            "limitations": list(self.limitations),
        }


def audit_source_inventory(
    database: SourceAuditDatabase,
    *,
    now: datetime | None = None,
    required_track_count: int = 10,
) -> SourceInventoryAudit:
    if not 1 <= required_track_count <= 50:
        raise ValueError("required_track_count must be between 1 and 50.")
    checked_at = _aware_utc(now or datetime.now(UTC))
    with database.system_transaction() as connection:
        row = connection.execute(
            """
            select
                count(distinct ce.candidate_recording_mbid)
                    filter (where ce.expires_at > %s) as fresh_candidate_count,
                count(distinct ce.candidate_recording_mbid)
                    filter (where ce.expires_at <= %s) as stale_candidate_count,
                count(distinct ce.candidate_recording_mbid)
                    filter (
                        where ce.expires_at > %s
                          and mapping.expires_at > %s
                    ) as fresh_spotify_mapping_count,
                count(distinct ce.candidate_recording_mbid)
                    filter (
                        where ce.expires_at > %s
                          and mapping.expires_at > %s
                          and (
                              ce.source_facts <> '{}'::jsonb
                              or ce.strength is not null
                              or ce.listener_count is not null
                          )
                    ) as evidenced_mapping_count
            from public.candidate_edges ce
            left join public.external_id_mappings mapping
              on mapping.recording_mbid = ce.candidate_recording_mbid
             and mapping.provider = 'spotify'
            """,
            (checked_at,) * 6,
        ).fetchone()
    values = row or {}
    candidate_count = _count(values.get("fresh_candidate_count"))
    stale_count = _count(values.get("stale_candidate_count"))
    mapping_count = _count(values.get("fresh_spotify_mapping_count"))
    evidence_count = _count(values.get("evidenced_mapping_count"))
    evidence_coverage = evidence_count / mapping_count if mapping_count else 0.0
    limitations: list[str] = []
    if candidate_count < required_track_count:
        limitations.append("insufficient_fresh_candidates")
    if mapping_count < required_track_count:
        limitations.append("insufficient_spotify_mappings")
    required_evidence_count = math.ceil(required_track_count * 0.9)
    if evidence_count < required_evidence_count:
        limitations.append("insufficient_evidence_coverage")
    return SourceInventoryAudit(
        status="ready" if not limitations else "insufficient",
        fresh_candidate_count=candidate_count,
        fresh_spotify_mapping_count=mapping_count,
        evidenced_mapping_count=evidence_count,
        stale_candidate_count=stale_count,
        evidence_coverage=round(evidence_coverage, 4),
        limitations=tuple(limitations),
    )


def _count(value: Any) -> int:
    return max(int(value or 0), 0)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Source audit timestamps must be timezone-aware.")
    return value.astimezone(UTC)
