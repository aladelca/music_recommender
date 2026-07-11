from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from psycopg.types.json import Jsonb

from music_recommender.storage.postgres import PostgresDatabase
from music_recommender.storage.protocols import (
    AccessStatus,
    ApplicationSessionRecord,
    ApprovedUserLimitError,
    BetaAccountRecord,
    CandidateEdgeRecord,
    CleanupResult,
    CompletedDiscoveryJobStatus,
    DiscoveryJobRecord,
    EvaluationCompletenessRecord,
    ExternalIdMappingRecord,
    ExternalIdProvider,
    FeedbackEventRecord,
    FeedbackEventReservation,
    MusicEntityRecord,
    OAuthStateRecord,
    PlaylistExportRecord,
    PlaylistExportReservation,
    PlaylistExportStatus,
    ProductFeedbackEventType,
    RecommendationItemRecord,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
    RecommendationStatus,
    SessionComparison,
    SessionEvaluationRecord,
    SourceCacheRecord,
    UserAccountRecord,
    UserPreferenceRecord,
    UserSeedInput,
    UserSeedRecord,
)


class PostgresUserRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def get(self, *, account_id: str) -> UserAccountRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select account_id, display_name, access_status, refresh_token_ciphertext,
                       token_scopes, token_issued_at, reauthorization_required, last_login_at,
                       created_at, updated_at
                from public.app_users
                where account_id = %s and deleted_at is null
                """,
                (account_id,),
            ).fetchone()
        return _user_from_row(row) if row is not None else None

    def upsert_pending(
        self,
        *,
        account_id: str,
        display_name: str | None,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
        login_at: datetime,
    ) -> UserAccountRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.app_users (
                    account_id, display_name, access_status, refresh_token_ciphertext,
                    token_scopes, token_issued_at, last_login_at
                )
                values (%s, %s, 'pending', %s, %s, %s, %s)
                on conflict (account_id) do update
                set display_name = excluded.display_name,
                    refresh_token_ciphertext = excluded.refresh_token_ciphertext,
                    token_scopes = excluded.token_scopes,
                    token_issued_at = excluded.token_issued_at,
                    last_login_at = excluded.last_login_at,
                    reauthorization_required = false
                where app_users.deleted_at is null
                returning account_id, display_name, access_status, refresh_token_ciphertext,
                          token_scopes, token_issued_at, reauthorization_required, last_login_at,
                          created_at, updated_at
                """,
                (
                    account_id,
                    display_name,
                    refresh_token_ciphertext,
                    list(token_scopes),
                    token_issued_at,
                    login_at,
                ),
            ).fetchone()
        if row is None:
            raise LookupError("Account is deleted and cannot be reactivated implicitly.")
        return _user_from_row(row)

    def set_access_status(
        self,
        *,
        account_id: str,
        status: AccessStatus,
    ) -> UserAccountRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                update public.app_users
                set access_status = %s
                where account_id = %s and deleted_at is null
                returning account_id, display_name, access_status, refresh_token_ciphertext,
                          token_scopes, token_issued_at, reauthorization_required, last_login_at,
                          created_at, updated_at
                """,
                (status, account_id),
            ).fetchone()
        if row is None:
            raise LookupError("Account not found.")
        return _user_from_row(row)

    def replace_refresh_token(
        self,
        *,
        account_id: str,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
    ) -> UserAccountRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.app_users
                set refresh_token_ciphertext = %s,
                    token_scopes = %s,
                    token_issued_at = %s,
                    reauthorization_required = false
                where account_id = %s and deleted_at is null
                returning account_id, display_name, access_status, refresh_token_ciphertext,
                          token_scopes, token_issued_at, reauthorization_required, last_login_at,
                          created_at, updated_at
                """,
                (
                    refresh_token_ciphertext,
                    list(token_scopes),
                    token_issued_at,
                    account_id,
                ),
            ).fetchone()
        if row is None:
            raise LookupError("Account not found.")
        return _user_from_row(row)


class PostgresOAuthStateRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def put(self, state: OAuthStateRecord) -> None:
        with self.database.system_transaction() as connection:
            connection.execute(
                """
                insert into public.oauth_states (
                    state_hash, verifier_ciphertext, return_path, expires_at, created_at
                )
                values (%s, %s, %s, %s, %s)
                """,
                (
                    state.state_hash,
                    state.verifier_ciphertext,
                    state.return_path,
                    state.expires_at,
                    state.created_at,
                ),
            )

    def consume(self, *, state_hash: str, now: datetime) -> OAuthStateRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select state_hash, verifier_ciphertext, return_path, expires_at, created_at
                from public.consume_oauth_state(%s, %s)
                """,
                (state_hash, now),
            ).fetchone()
        return _oauth_state_from_row(row) if row is not None else None


class PostgresApplicationSessionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def put(self, session: ApplicationSessionRecord) -> None:
        with self.database.transaction(account_id=session.account_id) as connection:
            connection.execute(
                """
                insert into public.app_sessions (
                    session_hash, account_id, csrf_hash, idle_expires_at,
                    absolute_expires_at, last_seen_at, revoked_at, created_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session.session_hash,
                    session.account_id,
                    session.csrf_hash,
                    session.idle_expires_at,
                    session.absolute_expires_at,
                    session.last_seen_at,
                    session.revoked_at,
                    session.created_at,
                ),
            )

    def get_active(
        self,
        *,
        session_hash: str,
        now: datetime,
    ) -> ApplicationSessionRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select session_hash, account_id, csrf_hash, idle_expires_at,
                       absolute_expires_at, last_seen_at, revoked_at, created_at
                from public.app_sessions
                where session_hash = %s
                  and revoked_at is null
                  and idle_expires_at > %s
                  and absolute_expires_at > %s
                """,
                (session_hash, now, now),
            ).fetchone()
        return _session_from_row(row) if row is not None else None

    def revoke(
        self,
        *,
        session_hash: str,
        account_id: str,
        revoked_at: datetime,
    ) -> bool:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.app_sessions
                set revoked_at = %s
                where session_hash = %s and account_id = %s and revoked_at is null
                returning session_hash
                """,
                (revoked_at, session_hash, account_id),
            ).fetchone()
        return row is not None

    def touch(
        self,
        *,
        session_hash: str,
        account_id: str,
        last_seen_at: datetime,
        idle_expires_at: datetime,
    ) -> ApplicationSessionRecord | None:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.app_sessions
                set last_seen_at = %s,
                    idle_expires_at = least(%s, absolute_expires_at)
                where session_hash = %s
                  and account_id = %s
                  and revoked_at is null
                  and idle_expires_at > %s
                  and absolute_expires_at > %s
                returning session_hash, account_id, csrf_hash, idle_expires_at,
                          absolute_expires_at, last_seen_at, revoked_at, created_at
                """,
                (
                    last_seen_at,
                    idle_expires_at,
                    session_hash,
                    account_id,
                    last_seen_at,
                    last_seen_at,
                ),
            ).fetchone()
        return _session_from_row(row) if row is not None else None


class PostgresBetaAccessRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def list_pending(self) -> tuple[BetaAccountRecord, ...]:
        with self.database.system_transaction() as connection:
            rows = connection.execute(
                """
                select account_id, access_status, last_login_at
                from public.app_users
                where access_status = 'pending' and deleted_at is null
                order by last_login_at desc nulls last, account_id
                limit 100
                """
            ).fetchall()
        return tuple(_beta_account_from_row(row) for row in rows)

    def get(self, *, account_id: str) -> BetaAccountRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select account_id, access_status, last_login_at
                from public.app_users
                where account_id = %s and deleted_at is null
                """,
                (account_id,),
            ).fetchone()
        return _beta_account_from_row(row) if row is not None else None

    def approved_count(self) -> int:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select count(*) as approved_count
                from public.app_users
                where access_status = 'approved' and deleted_at is null
                """
            ).fetchone()
        return int(_required_row(row)["approved_count"])

    def approve(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord:
        with self.database.system_transaction() as connection:
            connection.execute(
                "select pg_advisory_xact_lock("
                "hashtextextended('outside-the-loop-approved-users', 0))"
            )
            current = connection.execute(
                """
                select account_id, access_status, last_login_at
                from public.app_users
                where account_id = %s and deleted_at is null
                for update
                """,
                (account_id,),
            ).fetchone()
            if current is None:
                raise LookupError("Account not found.")
            if str(current["access_status"]) != "approved":
                count_row = connection.execute(
                    """
                    select count(*) as approved_count
                    from public.app_users
                    where access_status = 'approved' and deleted_at is null
                    """
                ).fetchone()
                if int(_required_row(count_row)["approved_count"]) >= 5:
                    raise ApprovedUserLimitError(
                        "Outside the Loop beta permits at most five approved users."
                    )
            row = connection.execute(
                """
                update public.app_users
                set access_status = 'approved', updated_at = %s
                where account_id = %s and deleted_at is null
                returning account_id, access_status, last_login_at
                """,
                (changed_at, account_id),
            ).fetchone()
        return _beta_account_from_row(_required_row(row))

    def revoke(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.app_users
                set access_status = 'revoked',
                    refresh_token_ciphertext = null,
                    token_scopes = '{}',
                    token_issued_at = null,
                    reauthorization_required = true,
                    updated_at = %s
                where account_id = %s and deleted_at is null
                returning account_id, access_status, last_login_at
                """,
                (changed_at, account_id),
            ).fetchone()
            if row is None:
                raise LookupError("Account not found.")
            connection.execute(
                """
                update public.app_sessions
                set revoked_at = %s
                where account_id = %s and revoked_at is null
                """,
                (changed_at, account_id),
            )
        return _beta_account_from_row(row)


class PostgresMusicEntityRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def upsert(self, entity: MusicEntityRecord) -> MusicEntityRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.music_entities (
                    mbid, entity_type, name, artist_credit, release_data, isrcs,
                    source, source_version, fetched_at, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (mbid) do update
                set name = excluded.name,
                    artist_credit = excluded.artist_credit,
                    release_data = excluded.release_data,
                    isrcs = excluded.isrcs,
                    source = excluded.source,
                    source_version = excluded.source_version,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                where music_entities.entity_type = excluded.entity_type
                returning mbid, entity_type, name, artist_credit, release_data, isrcs,
                          source, source_version, fetched_at, expires_at
                """,
                (
                    entity.mbid,
                    entity.entity_type,
                    entity.name,
                    Jsonb(list(entity.artist_credit)),
                    Jsonb(entity.release_data),
                    list(entity.isrcs),
                    entity.source,
                    entity.source_version,
                    entity.fetched_at,
                    entity.expires_at,
                ),
            ).fetchone()
        if row is None:
            raise ValueError("A MusicBrainz entity cannot change type.")
        return _music_entity_from_row(row)

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select mbid, entity_type, name, artist_credit, release_data, isrcs,
                       source, source_version, fetched_at, expires_at
                from public.music_entities
                where mbid = %s
                """,
                (mbid,),
            ).fetchone()
        return _music_entity_from_row(row) if row is not None else None

    def get_many(self, *, mbids: tuple[str, ...]) -> tuple[MusicEntityRecord, ...]:
        if not mbids:
            return ()
        with self.database.system_transaction() as connection:
            rows = connection.execute(
                """
                select mbid, entity_type, name, artist_credit, release_data, isrcs,
                       source, source_version, fetched_at, expires_at
                from public.music_entities
                where mbid = any(%s::uuid[])
                order by mbid
                """,
                (list(mbids),),
            ).fetchall()
        return tuple(_music_entity_from_row(row) for row in rows)


class PostgresUserSeedRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def replace_active(
        self,
        *,
        account_id: str,
        seeds: tuple[UserSeedInput, ...],
        selected_at: datetime,
    ) -> tuple[UserSeedRecord, ...]:
        if not 1 <= len(seeds) <= 5:
            raise ValueError("Between one and five seeds are required.")
        unique_seeds = {(seed.entity_type, seed.mbid) for seed in seeds}
        if len(unique_seeds) != len(seeds):
            raise ValueError("Seeds must be unique.")

        records: list[UserSeedRecord] = []
        with self.database.transaction(account_id=account_id) as connection:
            connection.execute(
                """
                update public.user_seeds
                set removed_at = %s
                where account_id = %s and removed_at is null
                """,
                (selected_at, account_id),
            )
            for position, seed in enumerate(seeds, start=1):
                row = connection.execute(
                    """
                    insert into public.user_seeds (
                        account_id, entity_type, mbid, display_name, position, selected_at
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    returning id, account_id, entity_type, mbid, display_name, position, selected_at
                    """,
                    (
                        account_id,
                        seed.entity_type,
                        seed.mbid,
                        seed.display_name,
                        position,
                        selected_at,
                    ),
                ).fetchone()
                records.append(_seed_from_row(_required_row(row)))
        return tuple(records)

    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]:
        with self.database.transaction(account_id=account_id) as connection:
            rows = connection.execute(
                """
                select id, account_id, entity_type, mbid, display_name, position, selected_at
                from public.user_seeds
                where account_id = %s and removed_at is null
                order by position, id
                """,
                (account_id,),
            ).fetchall()
        return tuple(_seed_from_row(row) for row in rows)


class PostgresSourceCacheRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def put(self, record: SourceCacheRecord) -> SourceCacheRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.source_cache_entries (
                    source, cache_key, status, normalized_payload, etag, fetched_at, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (source, cache_key) do update
                set status = excluded.status,
                    normalized_payload = excluded.normalized_payload,
                    etag = excluded.etag,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                returning source, cache_key, status, normalized_payload, etag,
                          fetched_at, expires_at
                """,
                (
                    record.source,
                    record.cache_key,
                    record.status,
                    Jsonb(record.normalized_payload),
                    record.etag,
                    record.fetched_at,
                    record.expires_at,
                ),
            ).fetchone()
        return _source_cache_from_row(_required_row(row))

    def get_fresh(
        self,
        *,
        source: str,
        cache_key: str,
        now: datetime,
    ) -> SourceCacheRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select source, cache_key, status, normalized_payload, etag,
                       fetched_at, expires_at
                from public.source_cache_entries
                where source = %s and cache_key = %s and expires_at > %s
                """,
                (source, cache_key, now),
            ).fetchone()
        return _source_cache_from_row(row) if row is not None else None


class PostgresSourceRateLimitRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def reserve(
        self,
        *,
        source: str,
        now: datetime,
        minimum_interval_seconds: float,
    ) -> datetime:
        if source not in {"musicbrainz", "listenbrainz", "listenbrainz_labs"}:
            raise ValueError("Unsupported external source rate limit.")
        if not 0.1 <= minimum_interval_seconds <= 60:
            raise ValueError("External source interval must be between 0.1 and 60 seconds.")
        interval = timedelta(seconds=minimum_interval_seconds)
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.source_rate_limits (source, next_allowed_at, updated_at)
                values (%s, %s::timestamptz + %s::interval, %s)
                on conflict (source) do update
                set next_allowed_at = greatest(
                        source_rate_limits.next_allowed_at,
                        excluded.next_allowed_at - %s::interval
                    ) + %s::interval,
                    updated_at = %s
                returning next_allowed_at - %s::interval as reserved_at
                """,
                (source, now, interval, now, interval, interval, now, interval),
            ).fetchone()
        return cast(datetime, _required_row(row)["reserved_at"])

    def defer(self, *, source: str, not_before: datetime) -> datetime:
        if source not in {"musicbrainz", "listenbrainz", "listenbrainz_labs"}:
            raise ValueError("Unsupported external source rate limit.")
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.source_rate_limits (source, next_allowed_at, updated_at)
                values (%s, %s, %s)
                on conflict (source) do update
                set next_allowed_at = greatest(
                        source_rate_limits.next_allowed_at,
                        excluded.next_allowed_at
                    ),
                    updated_at = excluded.updated_at
                returning next_allowed_at
                """,
                (source, not_before, not_before),
            ).fetchone()
        return cast(datetime, _required_row(row)["next_allowed_at"])


class PostgresCandidateEdgeRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def upsert(self, edge: CandidateEdgeRecord) -> CandidateEdgeRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.candidate_edges (
                    seed_mbid, candidate_recording_mbid, source_adapter,
                    algorithm_version, strength, listener_count, source_facts,
                    fetched_at, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (
                    seed_mbid, candidate_recording_mbid, source_adapter, algorithm_version
                ) do update
                set strength = excluded.strength,
                    listener_count = excluded.listener_count,
                    source_facts = excluded.source_facts,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                returning seed_mbid, candidate_recording_mbid, source_adapter,
                          algorithm_version, strength, listener_count, source_facts,
                          fetched_at, expires_at
                """,
                (
                    edge.seed_mbid,
                    edge.candidate_recording_mbid,
                    edge.source_adapter,
                    edge.algorithm_version,
                    edge.strength,
                    edge.listener_count,
                    Jsonb(edge.source_facts),
                    edge.fetched_at,
                    edge.expires_at,
                ),
            ).fetchone()
        return _candidate_edge_from_row(_required_row(row))

    def list_fresh(
        self,
        *,
        seed_mbids: tuple[str, ...],
        now: datetime,
    ) -> tuple[CandidateEdgeRecord, ...]:
        if not seed_mbids:
            return ()
        with self.database.system_transaction() as connection:
            rows = connection.execute(
                """
                select seed_mbid, candidate_recording_mbid, source_adapter,
                       algorithm_version, strength, listener_count, source_facts,
                       fetched_at, expires_at
                from public.candidate_edges
                where seed_mbid = any(%s::uuid[]) and expires_at > %s
                order by seed_mbid, source_adapter, candidate_recording_mbid
                """,
                (list(seed_mbids), now),
            ).fetchall()
        return tuple(_candidate_edge_from_row(row) for row in rows)


class PostgresExternalIdMappingRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def upsert(self, record: ExternalIdMappingRecord) -> ExternalIdMappingRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                insert into public.external_id_mappings (
                    recording_mbid, provider, provider_id, mapping_source,
                    confidence, fetched_at, expires_at
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (recording_mbid, provider) do update
                set provider_id = excluded.provider_id,
                    mapping_source = excluded.mapping_source,
                    confidence = excluded.confidence,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                returning recording_mbid, provider, provider_id, mapping_source,
                          confidence, fetched_at, expires_at
                """,
                (
                    record.recording_mbid,
                    record.provider,
                    record.provider_id,
                    record.mapping_source,
                    record.confidence,
                    record.fetched_at,
                    record.expires_at,
                ),
            ).fetchone()
        return _external_id_mapping_from_row(_required_row(row))

    def get_fresh(
        self,
        *,
        recording_mbid: str,
        provider: ExternalIdProvider,
        now: datetime,
    ) -> ExternalIdMappingRecord | None:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select recording_mbid, provider, provider_id, mapping_source,
                       confidence, fetched_at, expires_at
                from public.external_id_mappings
                where recording_mbid = %s and provider = %s and expires_at > %s
                """,
                (recording_mbid, provider, now),
            ).fetchone()
        return _external_id_mapping_from_row(row) if row is not None else None


class PostgresUserPreferenceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def get(self, *, account_id: str) -> UserPreferenceRecord | None:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                select account_id, blocked_artist_mbids, blocked_recording_mbids,
                       allow_explicit, created_at, updated_at
                from public.user_preferences
                where account_id = %s
                """,
                (account_id,),
            ).fetchone()
        return _user_preference_from_row(row) if row is not None else None

    def block_recording(
        self,
        *,
        account_id: str,
        recording_mbid: str,
        updated_at: datetime,
    ) -> UserPreferenceRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                insert into public.user_preferences (
                    account_id, blocked_recording_mbids, updated_at
                )
                values (%s, array[%s]::uuid[], %s)
                on conflict (account_id) do update
                set blocked_recording_mbids = array(
                        select distinct value
                        from unnest(
                            user_preferences.blocked_recording_mbids
                            || excluded.blocked_recording_mbids
                        ) as value
                        order by value
                    ),
                    updated_at = excluded.updated_at
                returning account_id, blocked_artist_mbids, blocked_recording_mbids,
                          allow_explicit, created_at, updated_at
                """,
                (account_id, recording_mbid, updated_at),
            ).fetchone()
        return _user_preference_from_row(_required_row(row))

    def block_artists(
        self,
        *,
        account_id: str,
        artist_mbids: tuple[str, ...],
        updated_at: datetime,
    ) -> UserPreferenceRecord:
        if not artist_mbids:
            raise ValueError("At least one artist MBID is required.")
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                insert into public.user_preferences (
                    account_id, blocked_artist_mbids, updated_at
                )
                values (%s, %s::uuid[], %s)
                on conflict (account_id) do update
                set blocked_artist_mbids = array(
                        select distinct value
                        from unnest(
                            user_preferences.blocked_artist_mbids
                            || excluded.blocked_artist_mbids
                        ) as value
                        order by value
                    ),
                    updated_at = excluded.updated_at
                returning account_id, blocked_artist_mbids, blocked_recording_mbids,
                          allow_explicit, created_at, updated_at
                """,
                (account_id, list(artist_mbids), updated_at),
            ).fetchone()
        return _user_preference_from_row(_required_row(row))

    def unblock_artist(
        self,
        *,
        account_id: str,
        artist_mbid: str,
        updated_at: datetime,
    ) -> UserPreferenceRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.user_preferences
                set blocked_artist_mbids = array(
                        select value
                        from unnest(blocked_artist_mbids) as value
                        where value <> %s::uuid
                        order by value
                    ),
                    updated_at = %s
                where account_id = %s
                returning account_id, blocked_artist_mbids, blocked_recording_mbids,
                          allow_explicit, created_at, updated_at
                """,
                (artist_mbid, updated_at, account_id),
            ).fetchone()
        if row is None:
            raise LookupError("User preferences were not found.")
        return _user_preference_from_row(row)


class PostgresRecommendationRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_with_items(
        self,
        *,
        session: RecommendationSessionRecord,
        items: tuple[RecommendationItemRecord, ...],
    ) -> RecommendationSessionBundle:
        with self.database.transaction(account_id=session.account_id) as connection:
            session_row = connection.execute(
                """
                insert into public.recommendation_sessions (
                    id, account_id, prompt, controls, parsed_intent, seed_ids,
                    source_snapshot, ranking_version, status, generated_at, updated_at,
                    reviewed_playlist_name, reviewed_playlist_public
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id, account_id, prompt, controls, parsed_intent, seed_ids,
                          source_snapshot, ranking_version, status, generated_at, updated_at,
                          reviewed_playlist_name, reviewed_playlist_public
                """,
                (
                    session.id,
                    session.account_id,
                    session.prompt,
                    Jsonb(session.controls),
                    Jsonb(session.parsed_intent),
                    list(session.seed_ids),
                    Jsonb(session.source_snapshot),
                    session.ranking_version,
                    session.status,
                    session.generated_at,
                    session.updated_at,
                    session.reviewed_playlist_name,
                    session.reviewed_playlist_public,
                ),
            ).fetchone()
            item_rows: list[Mapping[str, Any]] = []
            for item in items:
                if item.session_id != session.id:
                    raise ValueError("Recommendation item session does not match its parent.")
                item_row = connection.execute(
                    """
                    insert into public.recommendation_items (
                        session_id, recording_mbid, spotify_track_id, original_rank,
                        internal_score_components, evidence, display_snapshot,
                        selected, reviewed_order, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning session_id, recording_mbid, spotify_track_id, original_rank,
                              internal_score_components, evidence, display_snapshot,
                              selected, reviewed_order, created_at
                    """,
                    (
                        item.session_id,
                        item.recording_mbid,
                        item.spotify_track_id,
                        item.original_rank,
                        Jsonb(item.internal_score_components),
                        Jsonb(item.evidence),
                        Jsonb(item.display_snapshot),
                        item.selected,
                        item.reviewed_order,
                        item.created_at,
                    ),
                ).fetchone()
                item_rows.append(_required_row(item_row))
        return RecommendationSessionBundle(
            session=_recommendation_session_from_row(_required_row(session_row)),
            items=tuple(_recommendation_item_from_row(row) for row in item_rows),
        )

    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> RecommendationSessionBundle | None:
        with self.database.transaction(account_id=account_id) as connection:
            session_row = connection.execute(
                _RECOMMENDATION_SESSION_SELECT + " where id = %s and account_id = %s",
                (session_id, account_id),
            ).fetchone()
            if session_row is None:
                return None
            item_rows = connection.execute(
                _RECOMMENDATION_ITEM_SELECT + " where session_id = %s order by original_rank",
                (session_id,),
            ).fetchall()
        return RecommendationSessionBundle(
            session=_recommendation_session_from_row(session_row),
            items=tuple(_recommendation_item_from_row(row) for row in item_rows),
        )

    def list_sessions(
        self,
        *,
        account_id: str,
        limit: int,
        before_generated_at: datetime | None,
        before_id: str | None,
    ) -> tuple[RecommendationSessionRecord, ...]:
        if (before_generated_at is None) != (before_id is None):
            raise ValueError("Recommendation cursor values must be provided together.")
        with self.database.transaction(account_id=account_id) as connection:
            if before_generated_at is None:
                rows = connection.execute(
                    _RECOMMENDATION_SESSION_SELECT
                    + " where account_id = %s order by generated_at desc, id desc limit %s",
                    (account_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    _RECOMMENDATION_SESSION_SELECT
                    + """
                      where account_id = %s
                        and (generated_at, id) < (%s, %s::uuid)
                      order by generated_at desc, id desc
                      limit %s
                    """,
                    (account_id, before_generated_at, before_id, limit),
                ).fetchall()
        return tuple(_recommendation_session_from_row(row) for row in rows)

    def replace_selection(
        self,
        *,
        account_id: str,
        session_id: str,
        recording_mbids: tuple[str, ...],
        playlist_name: str,
        playlist_public: bool,
        reviewed_at: datetime,
    ) -> RecommendationSessionBundle | None:
        if len(set(recording_mbids)) != len(recording_mbids):
            raise ValueError("Reviewed recordings must be unique.")
        with self.database.transaction(account_id=account_id) as connection:
            session_row = connection.execute(
                """
                select id
                from public.recommendation_sessions
                where id = %s and account_id = %s
                for update
                """,
                (session_id, account_id),
            ).fetchone()
            if session_row is None:
                return None
            owned_rows = connection.execute(
                """
                select recording_mbid
                from public.recommendation_items
                where session_id = %s
                """,
                (session_id,),
            ).fetchall()
            owned_mbids = {str(row["recording_mbid"]) for row in owned_rows}
            if any(mbid not in owned_mbids for mbid in recording_mbids):
                raise ValueError("Reviewed recordings must belong to the recommendation session.")
            connection.execute(
                """
                update public.recommendation_items
                set selected = false, reviewed_order = null
                where session_id = %s
                """,
                (session_id,),
            )
            for reviewed_order, recording_mbid in enumerate(recording_mbids, start=1):
                connection.execute(
                    """
                    update public.recommendation_items
                    set selected = true, reviewed_order = %s
                    where session_id = %s and recording_mbid = %s
                    """,
                    (reviewed_order, session_id, recording_mbid),
                )
            updated_session = connection.execute(
                """
                update public.recommendation_sessions
                set status = 'reviewed',
                    reviewed_playlist_name = %s,
                    reviewed_playlist_public = %s,
                    updated_at = %s
                where id = %s and account_id = %s
                returning id, account_id, prompt, controls, parsed_intent, seed_ids,
                          source_snapshot, ranking_version, status, generated_at, updated_at,
                          reviewed_playlist_name, reviewed_playlist_public
                """,
                (playlist_name, playlist_public, reviewed_at, session_id, account_id),
            ).fetchone()
            item_rows = connection.execute(
                _RECOMMENDATION_ITEM_SELECT + " where session_id = %s order by original_rank",
                (session_id,),
            ).fetchall()
        return RecommendationSessionBundle(
            session=_recommendation_session_from_row(_required_row(updated_session)),
            items=tuple(_recommendation_item_from_row(row) for row in item_rows),
        )


_RECOMMENDATION_SESSION_SELECT = """
select id, account_id, prompt, controls, parsed_intent, seed_ids,
       source_snapshot, ranking_version, status, generated_at, updated_at,
       reviewed_playlist_name, reviewed_playlist_public
from public.recommendation_sessions
"""

_RECOMMENDATION_ITEM_SELECT = """
select session_id, recording_mbid, spotify_track_id, original_rank,
       internal_score_components, evidence, display_snapshot,
       selected, reviewed_order, created_at
from public.recommendation_items
"""


class PostgresPlaylistExportRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_or_get(self, record: PlaylistExportRecord) -> PlaylistExportReservation:
        with self.database.transaction(account_id=record.account_id) as connection:
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (record.session_id,),
            )
            existing = connection.execute(
                _PLAYLIST_EXPORT_SELECT
                + """
                  where session_id = %s
                     or (account_id = %s and idempotency_key = %s)
                  limit 1
                  for update
                """,
                (record.session_id, record.account_id, record.idempotency_key),
            ).fetchone()
            if existing is not None:
                return PlaylistExportReservation(
                    record=_playlist_export_from_row(existing),
                    created=False,
                )
            row = connection.execute(
                """
                insert into public.playlist_exports (
                    id, session_id, account_id, spotify_playlist_id, spotify_playlist_url,
                    name, description, public, recording_mbids, spotify_track_ids,
                    request_fingerprint, idempotency_key, status, tracks_added,
                    partial_failure, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id, session_id, account_id, spotify_playlist_id,
                          spotify_playlist_url, name, description, public, recording_mbids,
                          spotify_track_ids, request_fingerprint, idempotency_key, status,
                          tracks_added, partial_failure, created_at, updated_at
                """,
                (
                    record.id,
                    record.session_id,
                    record.account_id,
                    record.spotify_playlist_id,
                    record.spotify_playlist_url,
                    record.name,
                    record.description,
                    record.public,
                    list(record.recording_mbids),
                    list(record.spotify_track_ids),
                    record.request_fingerprint,
                    record.idempotency_key,
                    record.status,
                    record.tracks_added,
                    Jsonb(record.partial_failure) if record.partial_failure is not None else None,
                    record.created_at,
                    record.updated_at,
                ),
            ).fetchone()
        return PlaylistExportReservation(
            record=_playlist_export_from_row(_required_row(row)),
            created=True,
        )

    def set_playlist_created(
        self,
        *,
        account_id: str,
        export_id: str,
        spotify_playlist_id: str,
        spotify_playlist_url: str | None,
        updated_at: datetime,
    ) -> PlaylistExportRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.playlist_exports
                set spotify_playlist_id = %s,
                    spotify_playlist_url = %s,
                    status = 'adding_items',
                    partial_failure = null,
                    updated_at = %s
                where id = %s and account_id = %s
                  and (spotify_playlist_id is null or spotify_playlist_id = %s)
                returning id, session_id, account_id, spotify_playlist_id,
                          spotify_playlist_url, name, description, public, recording_mbids,
                          spotify_track_ids, request_fingerprint, idempotency_key, status,
                          tracks_added, partial_failure, created_at, updated_at
                """,
                (
                    spotify_playlist_id,
                    spotify_playlist_url,
                    updated_at,
                    export_id,
                    account_id,
                    spotify_playlist_id,
                ),
            ).fetchone()
        return _playlist_export_from_row(_required_row(row))

    def mark_complete(
        self,
        *,
        account_id: str,
        export_id: str,
        tracks_added: int,
        updated_at: datetime,
    ) -> PlaylistExportRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.playlist_exports
                set status = 'complete',
                    tracks_added = %s,
                    partial_failure = null,
                    updated_at = %s
                where id = %s and account_id = %s and spotify_playlist_id is not null
                returning id, session_id, account_id, spotify_playlist_id,
                          spotify_playlist_url, name, description, public, recording_mbids,
                          spotify_track_ids, request_fingerprint, idempotency_key, status,
                          tracks_added, partial_failure, created_at, updated_at
                """,
                (tracks_added, updated_at, export_id, account_id),
            ).fetchone()
            completed = _playlist_export_from_row(_required_row(row))
            connection.execute(
                """
                update public.recommendation_sessions
                set status = 'exported', updated_at = %s
                where id = %s and account_id = %s
                """,
                (updated_at, completed.session_id, account_id),
            )
        return completed

    def mark_partial_failure(
        self,
        *,
        account_id: str,
        export_id: str,
        error_code: str,
        updated_at: datetime,
    ) -> PlaylistExportRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.playlist_exports
                set status = 'partial_failure',
                    partial_failure = %s,
                    updated_at = %s
                where id = %s and account_id = %s
                returning id, session_id, account_id, spotify_playlist_id,
                          spotify_playlist_url, name, description, public, recording_mbids,
                          spotify_track_ids, request_fingerprint, idempotency_key, status,
                          tracks_added, partial_failure, created_at, updated_at
                """,
                (Jsonb({"code": error_code}), updated_at, export_id, account_id),
            ).fetchone()
        return _playlist_export_from_row(_required_row(row))


_PLAYLIST_EXPORT_SELECT = """
select id, session_id, account_id, spotify_playlist_id, spotify_playlist_url,
       name, description, public, recording_mbids, spotify_track_ids,
       request_fingerprint, idempotency_key, status, tracks_added,
       partial_failure, created_at, updated_at
from public.playlist_exports
"""


class PostgresFeedbackEventRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_or_get(self, record: FeedbackEventRecord) -> FeedbackEventReservation:
        with self.database.transaction(account_id=record.account_id) as connection:
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{record.account_id}:{record.idempotency_key}",),
            )
            existing = connection.execute(
                """
                select id, account_id, session_id, recording_mbid, event_type,
                       metadata, idempotency_key, created_at
                from public.feedback_events
                where account_id = %s and idempotency_key = %s
                for update
                """,
                (record.account_id, record.idempotency_key),
            ).fetchone()
            if existing is not None:
                return FeedbackEventReservation(
                    event=_feedback_event_from_row(existing),
                    created=False,
                )
            row = connection.execute(
                """
                insert into public.feedback_events (
                    id, account_id, session_id, recording_mbid, event_type,
                    metadata, idempotency_key, created_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning id, account_id, session_id, recording_mbid, event_type,
                          metadata, idempotency_key, created_at
                """,
                (
                    record.id,
                    record.account_id,
                    record.session_id,
                    record.recording_mbid,
                    record.event_type,
                    Jsonb(record.metadata),
                    record.idempotency_key,
                    record.created_at,
                ),
            ).fetchone()
        return FeedbackEventReservation(
            event=_feedback_event_from_row(_required_row(row)),
            created=True,
        )


class PostgresSessionEvaluationRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def upsert(self, record: SessionEvaluationRecord) -> SessionEvaluationRecord:
        with self.database.transaction(account_id=record.account_id) as connection:
            row = connection.execute(
                """
                insert into public.session_evaluations (
                    session_id, account_id, comparison, explanation_usefulness,
                    novelty_quality, comment, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (session_id) do update
                set comparison = excluded.comparison,
                    explanation_usefulness = excluded.explanation_usefulness,
                    novelty_quality = excluded.novelty_quality,
                    comment = excluded.comment,
                    updated_at = excluded.updated_at
                where session_evaluations.account_id = excluded.account_id
                returning session_id, account_id, comparison, explanation_usefulness,
                          novelty_quality, comment, created_at, updated_at
                """,
                (
                    record.session_id,
                    record.account_id,
                    record.comparison,
                    record.explanation_usefulness,
                    record.novelty_quality,
                    record.comment,
                    record.created_at,
                    record.updated_at,
                ),
            ).fetchone()
        if row is None:
            raise LookupError("Recommendation session was not found.")
        return _session_evaluation_from_row(row)

    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> SessionEvaluationRecord | None:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                select session_id, account_id, comparison, explanation_usefulness,
                       novelty_quality, comment, created_at, updated_at
                from public.session_evaluations
                where session_id = %s and account_id = %s
                """,
                (session_id, account_id),
            ).fetchone()
        return _session_evaluation_from_row(row) if row is not None else None

    def completeness(self) -> EvaluationCompletenessRecord:
        with self.database.system_transaction() as connection:
            row = connection.execute(
                """
                select
                    (
                        select count(*)
                        from public.app_users
                        where access_status = 'approved' and deleted_at is null
                    ) as approved_accounts,
                    count(distinct sessions.id) as eligible_sessions,
                    count(distinct evaluations.session_id) as completed_evaluations,
                    count(distinct evaluations.account_id) as accounts_with_evaluation
                from public.recommendation_sessions sessions
                left join public.session_evaluations evaluations
                  on evaluations.session_id = sessions.id
                 and evaluations.account_id = sessions.account_id
                where sessions.status in (
                    'ready', 'degraded', 'insufficient', 'reviewed', 'exported'
                )
                """
            ).fetchone()
        values = _required_row(row)
        return EvaluationCompletenessRecord(
            approved_accounts=int(values["approved_accounts"]),
            eligible_sessions=int(values["eligible_sessions"]),
            completed_evaluations=int(values["completed_evaluations"]),
            accounts_with_evaluation=int(values["accounts_with_evaluation"]),
        )


class PostgresAccountDeletionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def hard_delete(self, *, account_id: str) -> bool:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                delete from public.app_users
                where account_id = %s
                returning account_id
                """,
                (account_id,),
            ).fetchone()
        return row is not None


class PostgresCleanupRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def cleanup(self, *, now: datetime, batch_size: int) -> CleanupResult:
        if not 1 <= batch_size <= 10_000:
            raise ValueError("Cleanup batch size must be between 1 and 10000.")
        with self.database.system_transaction() as connection:
            oauth_states = _delete_count(
                connection,
                """
                delete from public.oauth_states
                where state_hash in (
                    select state_hash
                    from public.oauth_states
                    where expires_at <= %s
                       or consumed_at <= %s - interval '1 day'
                    order by expires_at
                    limit %s
                )
                """,
                (now, now, batch_size),
            )
            application_sessions = _delete_count(
                connection,
                """
                delete from public.app_sessions
                where session_hash in (
                    select session_hash
                    from public.app_sessions
                    where idle_expires_at <= %s
                       or absolute_expires_at <= %s
                       or revoked_at <= %s - interval '7 days'
                    order by idle_expires_at
                    limit %s
                )
                """,
                (now, now, now, batch_size),
            )
            source_cache_entries = _delete_count(
                connection,
                """
                delete from public.source_cache_entries
                where id in (
                    select id
                    from public.source_cache_entries
                    where expires_at <= %s
                    order by expires_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            candidate_edges = _delete_count(
                connection,
                """
                delete from public.candidate_edges
                where ctid in (
                    select ctid
                    from public.candidate_edges
                    where expires_at <= %s
                    order by expires_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            external_id_mappings = _delete_count(
                connection,
                """
                delete from public.external_id_mappings
                where ctid in (
                    select ctid
                    from public.external_id_mappings
                    where expires_at <= %s
                    order by expires_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            discovery_jobs = _delete_count(
                connection,
                """
                delete from public.discovery_jobs
                where id in (
                    select id
                    from public.discovery_jobs
                    where completed_at <= %s - interval '30 days'
                    order by completed_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            recommendation_sessions = _delete_count(
                connection,
                """
                delete from public.recommendation_sessions
                where id in (
                    select id
                    from public.recommendation_sessions
                    where generated_at <= %s - interval '180 days'
                    order by generated_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            removed_user_seeds = _delete_count(
                connection,
                """
                delete from public.user_seeds
                where id in (
                    select id
                    from public.user_seeds
                    where removed_at <= %s - interval '30 days'
                    order by removed_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
            music_entities = _delete_count(
                connection,
                """
                delete from public.music_entities entity
                where entity.mbid in (
                    select candidate.mbid
                    from public.music_entities candidate
                    where candidate.expires_at <= %s
                      and not exists (
                          select 1 from public.user_seeds seed
                          where seed.mbid = candidate.mbid
                      )
                      and not exists (
                          select 1 from public.candidate_edges edge
                          where edge.seed_mbid = candidate.mbid
                             or edge.candidate_recording_mbid = candidate.mbid
                      )
                      and not exists (
                          select 1 from public.recommendation_items item
                          where item.recording_mbid = candidate.mbid
                      )
                    order by candidate.expires_at
                    limit %s
                )
                """,
                (now, batch_size),
            )
        return CleanupResult(
            oauth_states=oauth_states,
            application_sessions=application_sessions,
            source_cache_entries=source_cache_entries,
            candidate_edges=candidate_edges,
            external_id_mappings=external_id_mappings,
            discovery_jobs=discovery_jobs,
            recommendation_sessions=recommendation_sessions,
            removed_user_seeds=removed_user_seeds,
            music_entities=music_entities,
        )


class PostgresDiscoveryJobRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_or_get(
        self,
        *,
        account_id: str,
        request_fingerprint: str,
        source_adapters: tuple[str, ...],
        queued_at: datetime,
    ) -> DiscoveryJobRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                insert into public.discovery_jobs (
                    account_id, request_fingerprint, source_adapters, queued_at
                )
                values (%s, %s, %s, %s)
                on conflict (account_id, request_fingerprint)
                    where status in ('queued', 'running')
                do update set source_adapters = discovery_jobs.source_adapters
                returning id, account_id, request_fingerprint, status, source_adapters,
                          attempt_count, error_code, queued_at, started_at, completed_at
                """,
                (account_id, request_fingerprint, list(source_adapters), queued_at),
            ).fetchone()
        return _discovery_job_from_row(_required_row(row))

    def get(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord | None:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                select id, account_id, request_fingerprint, status, source_adapters,
                       attempt_count, error_code, queued_at, started_at, completed_at
                from public.discovery_jobs
                where id = %s and account_id = %s
                """,
                (job_id, account_id),
            ).fetchone()
        return _discovery_job_from_row(row) if row is not None else None

    def claim(
        self,
        *,
        account_id: str,
        job_id: str,
        started_at: datetime,
        reclaim_started_before: datetime,
    ) -> DiscoveryJobRecord | None:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.discovery_jobs
                set status = 'running',
                    started_at = %s,
                    attempt_count = attempt_count + 1,
                    error_code = null
                where id = %s and account_id = %s
                  and (
                      status = 'queued'
                      or (status = 'running' and started_at <= %s)
                  )
                returning id, account_id, request_fingerprint, status, source_adapters,
                          attempt_count, error_code, queued_at, started_at, completed_at
                """,
                (started_at, job_id, account_id, reclaim_started_before),
            ).fetchone()
        return _discovery_job_from_row(row) if row is not None else None

    def complete(
        self,
        *,
        account_id: str,
        job_id: str,
        status: CompletedDiscoveryJobStatus,
        error_code: str | None,
        completed_at: datetime,
    ) -> DiscoveryJobRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.discovery_jobs
                set status = %s,
                    error_code = %s,
                    completed_at = %s
                where id = %s and account_id = %s and status = 'running'
                returning id, account_id, request_fingerprint, status, source_adapters,
                          attempt_count, error_code, queued_at, started_at, completed_at
                """,
                (status, error_code, completed_at, job_id, account_id),
            ).fetchone()
        return _discovery_job_from_row(_required_row(row))

    def release_for_retry(
        self,
        *,
        account_id: str,
        job_id: str,
        error_code: str,
    ) -> DiscoveryJobRecord:
        with self.database.transaction(account_id=account_id) as connection:
            row = connection.execute(
                """
                update public.discovery_jobs
                set status = 'queued',
                    error_code = %s,
                    started_at = null
                where id = %s and account_id = %s and status = 'running'
                returning id, account_id, request_fingerprint, status, source_adapters,
                          attempt_count, error_code, queued_at, started_at, completed_at
                """,
                (error_code, job_id, account_id),
            ).fetchone()
        return _discovery_job_from_row(_required_row(row))


class PostgresRepositories:
    def __init__(self, database: PostgresDatabase) -> None:
        self.users = PostgresUserRepository(database)
        self.oauth_states = PostgresOAuthStateRepository(database)
        self.sessions = PostgresApplicationSessionRepository(database)
        self.beta_access = PostgresBetaAccessRepository(database)
        self.music_entities = PostgresMusicEntityRepository(database)
        self.seeds = PostgresUserSeedRepository(database)
        self.source_cache = PostgresSourceCacheRepository(database)
        self.source_rate_limits = PostgresSourceRateLimitRepository(database)
        self.candidate_edges = PostgresCandidateEdgeRepository(database)
        self.external_id_mappings = PostgresExternalIdMappingRepository(database)
        self.user_preferences = PostgresUserPreferenceRepository(database)
        self.recommendations = PostgresRecommendationRepository(database)
        self.playlist_exports = PostgresPlaylistExportRepository(database)
        self.feedback_events = PostgresFeedbackEventRepository(database)
        self.session_evaluations = PostgresSessionEvaluationRepository(database)
        self.account_deletion = PostgresAccountDeletionRepository(database)
        self.cleanup = PostgresCleanupRepository(database)
        self.discovery_jobs = PostgresDiscoveryJobRepository(database)


def _required_row(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if row is None:
        raise RuntimeError("Database write did not return a record.")
    return row


def _delete_count(connection: Any, query: str, params: tuple[Any, ...]) -> int:
    result = connection.execute(query, params)
    return max(int(result.rowcount), 0)


def _user_from_row(row: Mapping[str, Any]) -> UserAccountRecord:
    return UserAccountRecord(
        account_id=str(row["account_id"]),
        display_name=_optional_str(row["display_name"]),
        access_status=cast(AccessStatus, str(row["access_status"])),
        refresh_token_ciphertext=(
            bytes(row["refresh_token_ciphertext"])
            if row["refresh_token_ciphertext"] is not None
            else None
        ),
        token_scopes=tuple(str(scope) for scope in row["token_scopes"]),
        token_issued_at=cast(datetime | None, row["token_issued_at"]),
        reauthorization_required=bool(row["reauthorization_required"]),
        last_login_at=cast(datetime | None, row["last_login_at"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _oauth_state_from_row(row: Mapping[str, Any]) -> OAuthStateRecord:
    return OAuthStateRecord(
        state_hash=str(row["state_hash"]),
        verifier_ciphertext=bytes(row["verifier_ciphertext"]),
        return_path=str(row["return_path"]),
        expires_at=cast(datetime, row["expires_at"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _session_from_row(row: Mapping[str, Any]) -> ApplicationSessionRecord:
    return ApplicationSessionRecord(
        session_hash=str(row["session_hash"]),
        account_id=str(row["account_id"]),
        csrf_hash=str(row["csrf_hash"]),
        idle_expires_at=cast(datetime, row["idle_expires_at"]),
        absolute_expires_at=cast(datetime, row["absolute_expires_at"]),
        last_seen_at=cast(datetime, row["last_seen_at"]),
        created_at=cast(datetime, row["created_at"]),
        revoked_at=cast(datetime | None, row["revoked_at"]),
    )


def _beta_account_from_row(row: Mapping[str, Any]) -> BetaAccountRecord:
    return BetaAccountRecord(
        account_id=str(row["account_id"]),
        access_status=cast(AccessStatus, str(row["access_status"])),
        last_login_at=cast(datetime | None, row["last_login_at"]),
    )


def _music_entity_from_row(row: Mapping[str, Any]) -> MusicEntityRecord:
    return MusicEntityRecord(
        mbid=str(row["mbid"]),
        entity_type=cast(Any, str(row["entity_type"])),
        name=str(row["name"]),
        artist_credit=tuple(dict(credit) for credit in row["artist_credit"]),
        release_data=dict(row["release_data"]),
        isrcs=tuple(str(isrc) for isrc in row["isrcs"]),
        source=cast(Any, str(row["source"])),
        source_version=_optional_str(row["source_version"]),
        fetched_at=cast(datetime, row["fetched_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )


def _seed_from_row(row: Mapping[str, Any]) -> UserSeedRecord:
    return UserSeedRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        entity_type=cast(Any, str(row["entity_type"])),
        mbid=str(row["mbid"]),
        display_name=str(row["display_name"]),
        position=int(row["position"]),
        selected_at=cast(datetime, row["selected_at"]),
    )


def _source_cache_from_row(row: Mapping[str, Any]) -> SourceCacheRecord:
    return SourceCacheRecord(
        source=cast(Any, str(row["source"])),
        cache_key=str(row["cache_key"]),
        status=cast(Any, str(row["status"])),
        normalized_payload=dict(row["normalized_payload"]),
        etag=_optional_str(row["etag"]),
        fetched_at=cast(datetime, row["fetched_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )


def _candidate_edge_from_row(row: Mapping[str, Any]) -> CandidateEdgeRecord:
    return CandidateEdgeRecord(
        seed_mbid=str(row["seed_mbid"]),
        candidate_recording_mbid=str(row["candidate_recording_mbid"]),
        source_adapter=cast(Any, str(row["source_adapter"])),
        algorithm_version=str(row["algorithm_version"]),
        strength=(float(row["strength"]) if row["strength"] is not None else None),
        listener_count=(int(row["listener_count"]) if row["listener_count"] is not None else None),
        source_facts=dict(row["source_facts"]),
        fetched_at=cast(datetime, row["fetched_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )


def _external_id_mapping_from_row(row: Mapping[str, Any]) -> ExternalIdMappingRecord:
    return ExternalIdMappingRecord(
        recording_mbid=str(row["recording_mbid"]),
        provider=cast(ExternalIdProvider, str(row["provider"])),
        provider_id=str(row["provider_id"]),
        mapping_source=str(row["mapping_source"]),
        confidence=(float(row["confidence"]) if row["confidence"] is not None else None),
        fetched_at=cast(datetime, row["fetched_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )


def _user_preference_from_row(row: Mapping[str, Any]) -> UserPreferenceRecord:
    return UserPreferenceRecord(
        account_id=str(row["account_id"]),
        blocked_artist_mbids=tuple(str(value) for value in row["blocked_artist_mbids"]),
        blocked_recording_mbids=tuple(str(value) for value in row["blocked_recording_mbids"]),
        allow_explicit=bool(row["allow_explicit"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _recommendation_session_from_row(
    row: Mapping[str, Any],
) -> RecommendationSessionRecord:
    return RecommendationSessionRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        prompt=str(row["prompt"]),
        controls=dict(row["controls"]),
        parsed_intent=dict(row["parsed_intent"]),
        seed_ids=tuple(str(value) for value in row["seed_ids"]),
        source_snapshot=dict(row["source_snapshot"]),
        ranking_version=str(row["ranking_version"]),
        status=cast(RecommendationStatus, str(row["status"])),
        generated_at=cast(datetime, row["generated_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        reviewed_playlist_name=_optional_str(row["reviewed_playlist_name"]),
        reviewed_playlist_public=(
            bool(row["reviewed_playlist_public"])
            if row["reviewed_playlist_public"] is not None
            else None
        ),
    )


def _recommendation_item_from_row(row: Mapping[str, Any]) -> RecommendationItemRecord:
    return RecommendationItemRecord(
        session_id=str(row["session_id"]),
        recording_mbid=str(row["recording_mbid"]),
        spotify_track_id=_optional_str(row["spotify_track_id"]),
        original_rank=int(row["original_rank"]),
        internal_score_components=dict(row["internal_score_components"]),
        evidence=dict(row["evidence"]),
        display_snapshot=dict(row["display_snapshot"]),
        selected=bool(row["selected"]),
        reviewed_order=(int(row["reviewed_order"]) if row["reviewed_order"] is not None else None),
        created_at=cast(datetime, row["created_at"]),
    )


def _playlist_export_from_row(row: Mapping[str, Any]) -> PlaylistExportRecord:
    partial_failure = row["partial_failure"]
    return PlaylistExportRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        account_id=str(row["account_id"]),
        spotify_playlist_id=_optional_str(row["spotify_playlist_id"]),
        spotify_playlist_url=_optional_str(row["spotify_playlist_url"]),
        name=str(row["name"]),
        description=str(row["description"]),
        public=bool(row["public"]),
        recording_mbids=tuple(str(value) for value in row["recording_mbids"]),
        spotify_track_ids=tuple(str(value) for value in row["spotify_track_ids"]),
        request_fingerprint=str(row["request_fingerprint"]),
        idempotency_key=str(row["idempotency_key"]),
        status=cast(PlaylistExportStatus, str(row["status"])),
        tracks_added=int(row["tracks_added"]),
        partial_failure=(dict(partial_failure) if partial_failure is not None else None),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _feedback_event_from_row(row: Mapping[str, Any]) -> FeedbackEventRecord:
    return FeedbackEventRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        session_id=str(row["session_id"]),
        recording_mbid=str(row["recording_mbid"]),
        event_type=cast(ProductFeedbackEventType, str(row["event_type"])),
        metadata=dict(row["metadata"]),
        idempotency_key=str(row["idempotency_key"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _session_evaluation_from_row(row: Mapping[str, Any]) -> SessionEvaluationRecord:
    return SessionEvaluationRecord(
        session_id=str(row["session_id"]),
        account_id=str(row["account_id"]),
        comparison=cast(SessionComparison, str(row["comparison"])),
        explanation_usefulness=int(row["explanation_usefulness"]),
        novelty_quality=int(row["novelty_quality"]),
        comment=_optional_str(row["comment"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _discovery_job_from_row(row: Mapping[str, Any]) -> DiscoveryJobRecord:
    return DiscoveryJobRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        request_fingerprint=str(row["request_fingerprint"]),
        status=cast(Any, str(row["status"])),
        source_adapters=tuple(str(adapter) for adapter in row["source_adapters"]),
        attempt_count=int(row["attempt_count"]),
        error_code=_optional_str(row["error_code"]),
        queued_at=cast(datetime, row["queued_at"]),
        started_at=cast(datetime | None, row["started_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
