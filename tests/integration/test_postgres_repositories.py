from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings
from music_recommender.storage.postgres_repositories import PostgresRepositories
from music_recommender.storage.protocols import (
    ApplicationSessionRecord,
    ApprovedUserLimitError,
    CandidateEdgeRecord,
    ExternalIdMappingRecord,
    FeedbackEventRecord,
    MusicEntityRecord,
    OAuthStateRecord,
    PlaylistExportRecord,
    RecommendationItemRecord,
    RecommendationSessionRecord,
    SessionEvaluationRecord,
    SourceCacheRecord,
    UserSeedInput,
)


def _database() -> PostgresDatabase:
    database_url = os.getenv("TEST_SUPABASE_DB_URL")
    if database_url is None:
        pytest.skip("Set TEST_SUPABASE_DB_URL to run Postgres repository integration tests.")
    return PostgresDatabase(PostgresPoolSettings(dsn=database_url))


def _clear_product_tables(database: PostgresDatabase) -> None:
    with database.system_transaction() as connection:
        connection.execute(
            """
            truncate table
                public.session_evaluations,
                public.playlist_exports,
                public.feedback_events,
                public.recommendation_items,
                public.recommendation_sessions,
                public.user_preferences,
                public.source_rate_limits,
                public.source_cache_entries,
                public.external_id_mappings,
                public.candidate_edges,
                public.discovery_jobs,
                public.user_seeds,
                public.music_entities,
                public.app_sessions,
                public.oauth_states,
                public.app_users
            restart identity cascade
            """
        )


def test_user_oauth_and_session_repositories_preserve_security_invariants() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 1, 1, tzinfo=UTC)

        account = repositories.users.upsert_pending(
            account_id="account-1",
            display_name="First Tester",
            refresh_token_ciphertext=b"encrypted-refresh-token",
            token_scopes=("playlist-modify-private",),
            token_issued_at=now,
            login_at=now,
        )
        assert account.access_status == "pending"
        assert account.refresh_token_ciphertext == b"encrypted-refresh-token"

        repositories.users.set_access_status(account_id="account-1", status="approved")
        relogged = repositories.users.upsert_pending(
            account_id="account-1",
            display_name="Updated Name",
            refresh_token_ciphertext=b"rotated-ciphertext",
            token_scopes=("playlist-modify-private", "playlist-modify-public"),
            token_issued_at=now + timedelta(minutes=1),
            login_at=now + timedelta(minutes=1),
        )
        assert relogged.access_status == "approved"
        assert relogged.display_name == "Updated Name"
        assert relogged.refresh_token_ciphertext == b"rotated-ciphertext"

        rotated = repositories.users.replace_refresh_token(
            account_id="account-1",
            refresh_token_ciphertext=b"worker-rotated-ciphertext",
            token_scopes=("playlist-modify-private", "playlist-modify-public"),
            token_issued_at=now + timedelta(minutes=2),
        )
        assert rotated.refresh_token_ciphertext == b"worker-rotated-ciphertext"
        assert rotated.access_status == "approved"

        oauth_state = OAuthStateRecord(
            state_hash="a" * 64,
            verifier_ciphertext=b"encrypted-verifier",
            return_path="/discover",
            expires_at=now + timedelta(minutes=10),
            created_at=now,
        )
        repositories.oauth_states.put(oauth_state)
        assert repositories.oauth_states.consume(state_hash="a" * 64, now=now) == oauth_state
        assert repositories.oauth_states.consume(state_hash="a" * 64, now=now) is None

        session = ApplicationSessionRecord(
            session_hash="b" * 64,
            account_id="account-1",
            csrf_hash="c" * 64,
            idle_expires_at=now + timedelta(days=7),
            absolute_expires_at=now + timedelta(days=30),
            last_seen_at=now,
            created_at=now,
        )
        repositories.sessions.put(session)
        loaded_session = repositories.sessions.get_active(session_hash="b" * 64, now=now)
        assert loaded_session == session

        touched_session = repositories.sessions.touch(
            session_hash="b" * 64,
            account_id="account-1",
            last_seen_at=now + timedelta(days=6),
            idle_expires_at=now + timedelta(days=36),
        )
        assert touched_session is not None
        assert touched_session.last_seen_at == now + timedelta(days=6)
        assert touched_session.idle_expires_at == session.absolute_expires_at

        assert repositories.sessions.revoke(
            session_hash="b" * 64,
            account_id="account-1",
            revoked_at=now + timedelta(minutes=5),
        )
        assert repositories.sessions.get_active(session_hash="b" * 64, now=now) is None
    finally:
        database.close()


def test_seed_entity_cache_and_discovery_repositories_are_account_scoped() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 1, 1, tzinfo=UTC)
        later = now + timedelta(hours=1)

        for account_id in ("account-1", "account-2"):
            repositories.users.upsert_pending(
                account_id=account_id,
                display_name=None,
                refresh_token_ciphertext=b"ciphertext",
                token_scopes=("playlist-modify-private",),
                token_issued_at=now,
                login_at=now,
            )

        entities = (
            MusicEntityRecord(
                mbid="10000000-0000-0000-0000-000000000001",
                entity_type="artist",
                name="Portishead",
                artist_credit=(),
                release_data={},
                isrcs=(),
                source="musicbrainz",
                source_version=None,
                fetched_at=now,
                expires_at=now + timedelta(days=30),
            ),
            MusicEntityRecord(
                mbid="10000000-0000-0000-0000-000000000002",
                entity_type="recording",
                name="Roads",
                artist_credit=({"name": "Portishead"},),
                release_data={},
                isrcs=(),
                source="musicbrainz",
                source_version=None,
                fetched_at=now,
                expires_at=now + timedelta(days=30),
            ),
        )
        for entity in entities:
            repositories.music_entities.upsert(entity)

        selected = repositories.seeds.replace_active(
            account_id="account-1",
            seeds=(
                UserSeedInput(
                    entity_type="artist",
                    mbid=entities[0].mbid,
                    display_name=entities[0].name,
                ),
                UserSeedInput(
                    entity_type="recording",
                    mbid=entities[1].mbid,
                    display_name=entities[1].name,
                ),
            ),
            selected_at=now,
        )
        assert [seed.position for seed in selected] == [1, 2]
        assert repositories.seeds.list_active(account_id="account-2") == ()
        assert repositories.seeds.list_active(account_id="account-1") == selected

        cache_record = SourceCacheRecord(
            source="musicbrainz",
            cache_key="artist-search:portishead",
            status="fresh",
            normalized_payload={"results": [{"mbid": entities[0].mbid}]},
            etag=None,
            fetched_at=now,
            expires_at=later,
        )
        repositories.source_cache.put(cache_record)
        assert (
            repositories.source_cache.get_fresh(
                source="musicbrainz",
                cache_key="artist-search:portishead",
                now=now,
            )
            == cache_record
        )
        assert (
            repositories.source_cache.get_fresh(
                source="musicbrainz",
                cache_key="artist-search:portishead",
                now=later,
            )
            is None
        )

        first_job = repositories.discovery_jobs.create_or_get(
            account_id="account-1",
            request_fingerprint="d" * 64,
            source_adapters=("musicbrainz", "listenbrainz"),
            queued_at=now,
        )
        replayed_job = repositories.discovery_jobs.create_or_get(
            account_id="account-1",
            request_fingerprint="d" * 64,
            source_adapters=("musicbrainz", "listenbrainz"),
            queued_at=now + timedelta(seconds=1),
        )
        assert replayed_job.id == first_job.id
        assert (
            repositories.discovery_jobs.get(
                account_id="account-2",
                job_id=first_job.id,
            )
            is None
        )
        assert (
            repositories.discovery_jobs.get(
                account_id="account-1",
                job_id=first_job.id,
            )
            == first_job
        )
        claimed = repositories.discovery_jobs.claim(
            account_id="account-1",
            job_id=first_job.id,
            started_at=now + timedelta(seconds=2),
            reclaim_started_before=now - timedelta(seconds=148),
        )
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.attempt_count == 1
        fresh_duplicate = repositories.discovery_jobs.claim(
            account_id="account-1",
            job_id=first_job.id,
            started_at=now + timedelta(seconds=100),
            reclaim_started_before=now - timedelta(seconds=50),
        )
        assert fresh_duplicate is None
        reclaimed = repositories.discovery_jobs.claim(
            account_id="account-1",
            job_id=first_job.id,
            started_at=now + timedelta(seconds=200),
            reclaim_started_before=now + timedelta(seconds=50),
        )
        assert reclaimed is not None
        assert reclaimed.attempt_count == 2
        released = repositories.discovery_jobs.release_for_retry(
            account_id="account-1",
            job_id=first_job.id,
            error_code="discovery_source_unavailable",
        )
        assert released.status == "queued"
        assert released.error_code == "discovery_source_unavailable"
        claimed = repositories.discovery_jobs.claim(
            account_id="account-1",
            job_id=first_job.id,
            started_at=now + timedelta(seconds=201),
            reclaim_started_before=now + timedelta(seconds=51),
        )
        assert claimed is not None
        assert claimed.attempt_count == 3
        completed = repositories.discovery_jobs.complete(
            account_id="account-1",
            job_id=first_job.id,
            status="ready",
            error_code=None,
            completed_at=now + timedelta(seconds=4),
        )
        assert completed.status == "ready"

        candidate = MusicEntityRecord(
            mbid="10000000-0000-0000-0000-000000000003",
            entity_type="recording",
            name="10000000-0000-0000-0000-000000000003",
            artist_credit=({"name": "Candidate Artist"},),
            release_data={"metadata_pending": True},
            isrcs=(),
            source="listenbrainz",
            source_version="core-v1",
            fetched_at=now,
            expires_at=later,
        )
        repositories.music_entities.upsert(candidate)
        edge = CandidateEdgeRecord(
            seed_mbid=entities[0].mbid,
            candidate_recording_mbid=candidate.mbid,
            source_adapter="listenbrainz_artist_radio",
            algorithm_version="lb-core-v1",
            strength=None,
            listener_count=100,
            source_facts={"similar_artist_name": "Candidate Artist"},
            fetched_at=now,
            expires_at=later,
        )
        assert repositories.candidate_edges.upsert(edge) == edge
        assert repositories.candidate_edges.list_fresh(
            seed_mbids=(entities[0].mbid,),
            now=now,
        ) == (edge,)
        mapping = ExternalIdMappingRecord(
            recording_mbid=candidate.mbid,
            provider="spotify",
            provider_id="spotify-track-1",
            mapping_source="isrc_exact",
            confidence=1.0,
            fetched_at=now,
            expires_at=later,
        )
        assert repositories.external_id_mappings.upsert(mapping) == mapping
        assert (
            repositories.external_id_mappings.get_fresh(
                recording_mbid=candidate.mbid,
                provider="spotify",
                now=now,
            )
            == mapping
        )
        assert (
            repositories.external_id_mappings.get_fresh(
                recording_mbid=candidate.mbid,
                provider="spotify",
                now=later,
            )
            is None
        )
        recommendation_session = RecommendationSessionRecord(
            id="40000000-0000-0000-0000-000000000001",
            account_id="account-1",
            prompt="Late night discovery",
            controls={"adventure": "balanced", "allow_explicit": True},
            parsed_intent={"label": "seed-led", "tags": []},
            seed_ids=tuple(seed.id for seed in selected),
            source_snapshot={"coverage": {"status": "ready"}},
            ranking_version="explicit-discovery-v1",
            status="ready",
            generated_at=now,
            updated_at=now,
            reviewed_playlist_name=None,
            reviewed_playlist_public=None,
        )
        recommendation_item = RecommendationItemRecord(
            session_id=recommendation_session.id,
            recording_mbid=candidate.mbid,
            spotify_track_id=mapping.provider_id,
            original_rank=1,
            internal_score_components={"total": 0.8},
            evidence={"evidence_version": "evidence-v1", "verifiable": True},
            display_snapshot={"name": "Candidate", "explicit": False},
            selected=True,
            reviewed_order=None,
            created_at=now,
        )
        recommendation_bundle = repositories.recommendations.create_with_items(
            session=recommendation_session,
            items=(recommendation_item,),
        )
        assert recommendation_bundle.session == recommendation_session
        assert recommendation_bundle.items == (recommendation_item,)
        assert (
            repositories.recommendations.get(
                account_id="account-2",
                session_id=recommendation_session.id,
            )
            is None
        )
        assert repositories.recommendations.list_sessions(
            account_id="account-1",
            limit=10,
            before_generated_at=None,
            before_id=None,
        ) == (recommendation_session,)
        with pytest.raises(ValueError, match="belong"):
            repositories.recommendations.replace_selection(
                account_id="account-1",
                session_id=recommendation_session.id,
                recording_mbids=("30000000-0000-0000-0000-000000000099",),
                playlist_name="Invalid",
                playlist_public=False,
                reviewed_at=later,
            )
        assert (
            repositories.recommendations.get(
                account_id="account-1",
                session_id=recommendation_session.id,
            )
            == recommendation_bundle
        )
        reviewed = repositories.recommendations.replace_selection(
            account_id="account-1",
            session_id=recommendation_session.id,
            recording_mbids=(candidate.mbid,),
            playlist_name="Late Night Finds",
            playlist_public=True,
            reviewed_at=later,
        )
        assert reviewed is not None
        assert reviewed.session.status == "reviewed"
        assert reviewed.session.reviewed_playlist_name == "Late Night Finds"
        assert reviewed.items[0].reviewed_order == 1
        playlist_export = PlaylistExportRecord(
            id="50000000-0000-0000-0000-000000000001",
            session_id=recommendation_session.id,
            account_id="account-1",
            spotify_playlist_id=None,
            spotify_playlist_url=None,
            name="Late Night Finds",
            description="Reviewed discoveries",
            public=True,
            recording_mbids=(candidate.mbid,),
            spotify_track_ids=(mapping.provider_id,),
            request_fingerprint="e" * 64,
            idempotency_key="export-key-1",
            status="creating",
            tracks_added=0,
            partial_failure=None,
            created_at=later,
            updated_at=later,
        )
        first_export_reservation = repositories.playlist_exports.create_or_get(playlist_export)
        replayed_export_reservation = repositories.playlist_exports.create_or_get(playlist_export)
        assert first_export_reservation.record == playlist_export
        assert first_export_reservation.created is True
        assert replayed_export_reservation.record == playlist_export
        assert replayed_export_reservation.created is False
        playlist_created = repositories.playlist_exports.set_playlist_created(
            account_id="account-1",
            export_id=playlist_export.id,
            spotify_playlist_id="spotify-playlist-1",
            spotify_playlist_url="https://open.spotify.com/playlist/spotify-playlist-1",
            updated_at=later + timedelta(seconds=1),
        )
        assert playlist_created.status == "adding_items"
        partial = repositories.playlist_exports.mark_partial_failure(
            account_id="account-1",
            export_id=playlist_export.id,
            error_code="spotify_service_unavailable",
            updated_at=later + timedelta(seconds=2),
        )
        assert partial.status == "partial_failure"
        assert partial.partial_failure == {"code": "spotify_service_unavailable"}
        exported = repositories.playlist_exports.mark_complete(
            account_id="account-1",
            export_id=playlist_export.id,
            tracks_added=1,
            updated_at=later + timedelta(seconds=3),
        )
        assert exported.status == "complete"
        assert exported.tracks_added == 1
        exported_session = repositories.recommendations.get(
            account_id="account-1",
            session_id=recommendation_session.id,
        )
        assert exported_session is not None
        assert exported_session.session.status == "exported"
        feedback_event = FeedbackEventRecord(
            id="60000000-0000-0000-0000-000000000001",
            account_id="account-1",
            session_id=recommendation_session.id,
            recording_mbid=candidate.mbid,
            event_type="dislike",
            metadata={"reason": "Not for me"},
            idempotency_key="feedback-key-1",
            created_at=later,
        )
        feedback_reservation = repositories.feedback_events.create_or_get(feedback_event)
        assert feedback_reservation.created is True
        assert feedback_reservation.event == feedback_event
        assert repositories.feedback_events.create_or_get(feedback_event).created is False
        recording_preference = repositories.user_preferences.block_recording(
            account_id="account-1",
            recording_mbid=candidate.mbid,
            updated_at=later,
        )
        assert recording_preference.blocked_recording_mbids == (candidate.mbid,)
        artist_preference = repositories.user_preferences.block_artists(
            account_id="account-1",
            artist_mbids=(entities[0].mbid,),
            updated_at=later,
        )
        assert artist_preference.blocked_artist_mbids == (entities[0].mbid,)
        unblocked_preference = repositories.user_preferences.unblock_artist(
            account_id="account-1",
            artist_mbid=entities[0].mbid,
            updated_at=later + timedelta(seconds=1),
        )
        assert unblocked_preference.blocked_artist_mbids == ()
        evaluation = SessionEvaluationRecord(
            session_id=recommendation_session.id,
            account_id="account-1",
            comparison="better",
            explanation_usefulness=5,
            novelty_quality=4,
            comment="Useful evidence.",
            created_at=later,
            updated_at=later,
        )
        assert repositories.session_evaluations.upsert(evaluation) == evaluation
        assert (
            repositories.session_evaluations.get(
                account_id="account-1",
                session_id=recommendation_session.id,
            )
            == evaluation
        )
        assert (
            repositories.session_evaluations.get(
                account_id="account-2",
                session_id=recommendation_session.id,
            )
            is None
        )
        completeness = repositories.session_evaluations.completeness()
        assert completeness.eligible_sessions == 1
        assert completeness.completed_evaluations == 1
        assert completeness.accounts_with_evaluation == 1
    finally:
        database.close()


def test_beta_access_repository_caps_approvals_and_revocation_clears_credentials() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 1, 1, tzinfo=UTC)
        for index in range(1, 7):
            repositories.users.upsert_pending(
                account_id=f"account-{index}",
                display_name=f"Tester {index}",
                refresh_token_ciphertext=f"ciphertext-{index}".encode(),
                token_scopes=("playlist-modify-private",),
                token_issued_at=now,
                login_at=now,
            )

        for index in range(1, 6):
            repositories.beta_access.approve(
                account_id=f"account-{index}",
                changed_at=now,
            )
        with pytest.raises(ApprovedUserLimitError):
            repositories.beta_access.approve(account_id="account-6", changed_at=now)

        repositories.sessions.put(
            ApplicationSessionRecord(
                session_hash="f" * 64,
                account_id="account-1",
                csrf_hash="e" * 64,
                idle_expires_at=now + timedelta(days=7),
                absolute_expires_at=now + timedelta(days=30),
                last_seen_at=now,
                created_at=now,
            )
        )
        revoked = repositories.beta_access.revoke(
            account_id="account-1",
            changed_at=now + timedelta(minutes=1),
        )

        assert revoked.access_status == "revoked"
        account = repositories.users.get(account_id="account-1")
        assert account is not None
        assert account.refresh_token_ciphertext is None
        assert account.token_scopes == ()
        assert account.reauthorization_required is True
        assert repositories.sessions.get_active(session_hash="f" * 64, now=now) is None
        assert repositories.beta_access.approved_count() == 4
    finally:
        database.close()


def test_source_rate_limit_repository_reserves_global_one_second_slots() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 1, 1, tzinfo=UTC)

        first = repositories.source_rate_limits.reserve(
            source="musicbrainz",
            now=now,
            minimum_interval_seconds=1.0,
        )
        second = repositories.source_rate_limits.reserve(
            source="musicbrainz",
            now=now,
            minimum_interval_seconds=1.0,
        )
        after_idle = repositories.source_rate_limits.reserve(
            source="musicbrainz",
            now=now + timedelta(seconds=5),
            minimum_interval_seconds=1.0,
        )

        assert first == now
        assert second == now + timedelta(seconds=1)
        assert after_idle == now + timedelta(seconds=5)
    finally:
        database.close()


def test_account_hard_deletion_cascades_all_user_owned_product_records() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 1, 1, tzinfo=UTC)
        repositories.users.upsert_pending(
            account_id="delete-me",
            display_name="Delete Me",
            refresh_token_ciphertext=b"encrypted-token",
            token_scopes=("playlist-modify-private",),
            token_issued_at=now,
            login_at=now,
        )
        entity = MusicEntityRecord(
            mbid="70000000-0000-0000-0000-000000000001",
            entity_type="recording",
            name="Delete Test",
            artist_credit=(),
            release_data={},
            isrcs=(),
            source="musicbrainz",
            source_version=None,
            fetched_at=now,
            expires_at=now + timedelta(days=30),
        )
        repositories.music_entities.upsert(entity)
        selected = repositories.seeds.replace_active(
            account_id="delete-me",
            seeds=(
                UserSeedInput(
                    entity_type="recording",
                    mbid=entity.mbid,
                    display_name=entity.name,
                ),
            ),
            selected_at=now,
        )
        repositories.sessions.put(
            ApplicationSessionRecord(
                session_hash="9" * 64,
                account_id="delete-me",
                csrf_hash="8" * 64,
                idle_expires_at=now + timedelta(days=7),
                absolute_expires_at=now + timedelta(days=30),
                last_seen_at=now,
                created_at=now,
            )
        )
        session = RecommendationSessionRecord(
            id="71000000-0000-0000-0000-000000000001",
            account_id="delete-me",
            prompt="Delete this",
            controls={},
            parsed_intent={},
            seed_ids=(selected[0].id,),
            source_snapshot={},
            ranking_version="explicit-discovery-v1",
            status="ready",
            generated_at=now,
            updated_at=now,
            reviewed_playlist_name=None,
            reviewed_playlist_public=None,
        )
        item = RecommendationItemRecord(
            session_id=session.id,
            recording_mbid=entity.mbid,
            spotify_track_id="spotify-delete",
            original_rank=1,
            internal_score_components={},
            evidence={},
            display_snapshot={},
            selected=True,
            reviewed_order=None,
            created_at=now,
        )
        repositories.recommendations.create_with_items(session=session, items=(item,))
        repositories.feedback_events.create_or_get(
            FeedbackEventRecord(
                id="72000000-0000-0000-0000-000000000001",
                account_id="delete-me",
                session_id=session.id,
                recording_mbid=entity.mbid,
                event_type="like",
                metadata={},
                idempotency_key="delete-feedback",
                created_at=now,
            )
        )
        repositories.session_evaluations.upsert(
            SessionEvaluationRecord(
                session_id=session.id,
                account_id="delete-me",
                comparison="same",
                explanation_usefulness=3,
                novelty_quality=3,
                comment=None,
                created_at=now,
                updated_at=now,
            )
        )

        assert repositories.account_deletion.hard_delete(account_id="delete-me") is True

        with database.system_transaction() as connection:
            counts = connection.execute(
                """
                select
                    (select count(*) from public.app_users where account_id = 'delete-me') users,
                    (
                        select count(*) from public.app_sessions
                        where account_id = 'delete-me'
                    ) sessions,
                    (select count(*) from public.user_seeds where account_id = 'delete-me') seeds,
                    (
                        select count(*) from public.recommendation_sessions
                        where account_id = 'delete-me'
                    ) recommendations,
                    (
                        select count(*) from public.feedback_events
                        where account_id = 'delete-me'
                    ) feedback,
                    (
                        select count(*) from public.session_evaluations
                        where account_id = 'delete-me'
                    ) evaluations
                """
            ).fetchone()
        assert counts is not None
        assert all(int(value) == 0 for value in counts.values())
        assert repositories.users.get(account_id="delete-me") is None
    finally:
        database.close()


def test_cleanup_repository_removes_expired_data_in_bounded_batches() -> None:
    database = _database()
    try:
        _clear_product_tables(database)
        repositories = PostgresRepositories(database)
        now = datetime(2030, 7, 1, tzinfo=UTC)
        with database.system_transaction() as connection:
            connection.execute(
                "insert into public.app_users (account_id) values ('cleanup-account')"
            )
            connection.execute(
                """
                insert into public.oauth_states (
                    state_hash, verifier_ciphertext, return_path, expires_at, created_at
                )
                values (%s, %s, '/discover', %s, %s)
                """,
                ("7" * 64, b"ciphertext", now - timedelta(days=1), now - timedelta(days=2)),
            )
            connection.execute(
                """
                insert into public.app_sessions (
                    session_hash, account_id, csrf_hash, idle_expires_at,
                    absolute_expires_at, last_seen_at, created_at
                )
                values (%s, 'cleanup-account', %s, %s, %s, %s, %s)
                """,
                (
                    "6" * 64,
                    "5" * 64,
                    now - timedelta(days=20),
                    now - timedelta(days=10),
                    now - timedelta(days=30),
                    now - timedelta(days=40),
                ),
            )
            connection.execute(
                """
                insert into public.music_entities (
                    mbid, entity_type, name, source, fetched_at, expires_at
                )
                values
                    (
                        '73000000-0000-0000-0000-000000000001',
                        'artist', 'Expired Seed', 'musicbrainz', %s, %s
                    ),
                    (
                        '73000000-0000-0000-0000-000000000002',
                        'recording', 'Expired Candidate', 'listenbrainz', %s, %s
                    )
                """,
                (
                    now - timedelta(days=40),
                    now - timedelta(days=10),
                    now - timedelta(days=40),
                    now - timedelta(days=10),
                ),
            )
            connection.execute(
                """
                insert into public.user_seeds (
                    id, account_id, entity_type, mbid, display_name,
                    position, selected_at, removed_at
                )
                values (
                    '74000000-0000-0000-0000-000000000001', 'cleanup-account',
                    'artist', '73000000-0000-0000-0000-000000000001',
                    'Expired Seed', 1, %s, %s
                )
                """,
                (now - timedelta(days=60), now - timedelta(days=40)),
            )
            connection.execute(
                """
                insert into public.candidate_edges (
                    seed_mbid, candidate_recording_mbid, source_adapter,
                    algorithm_version, source_facts, fetched_at, expires_at
                )
                values (
                    '73000000-0000-0000-0000-000000000001',
                    '73000000-0000-0000-0000-000000000002',
                    'listenbrainz_artist_radio', 'lb-core-v1', '{}', %s, %s
                )
                """,
                (now - timedelta(days=10), now - timedelta(days=1)),
            )
            connection.execute(
                """
                insert into public.external_id_mappings (
                    recording_mbid, provider, provider_id, mapping_source,
                    confidence, fetched_at, expires_at
                )
                values (
                    '73000000-0000-0000-0000-000000000002', 'spotify',
                    'expired-spotify', 'isrc_exact', 1, %s, %s
                )
                """,
                (now - timedelta(days=2), now - timedelta(days=1)),
            )
            connection.execute(
                """
                insert into public.source_cache_entries (
                    source, cache_key, status, normalized_payload, fetched_at, expires_at
                )
                values ('listenbrainz', 'expired', 'fresh', '{}', %s, %s)
                """,
                (now - timedelta(days=2), now - timedelta(days=1)),
            )
            connection.execute(
                """
                insert into public.discovery_jobs (
                    id, account_id, request_fingerprint, status,
                    completed_at, queued_at
                )
                values (
                    '75000000-0000-0000-0000-000000000001', 'cleanup-account',
                    %s, 'ready', %s, %s
                )
                """,
                ("4" * 64, now - timedelta(days=40), now - timedelta(days=41)),
            )
            connection.execute(
                """
                insert into public.recommendation_sessions (
                    id, account_id, prompt, seed_ids, ranking_version,
                    status, generated_at, updated_at
                )
                values (
                    '76000000-0000-0000-0000-000000000001', 'cleanup-account',
                    'Old recommendation', array['74000000-0000-0000-0000-000000000001']::uuid[],
                    'explicit-discovery-v1', 'ready', %s, %s
                )
                """,
                (now - timedelta(days=200), now - timedelta(days=200)),
            )

        result = repositories.cleanup.cleanup(now=now, batch_size=100)

        assert result.to_dict() == {
            "oauth_states": 1,
            "application_sessions": 1,
            "source_cache_entries": 1,
            "candidate_edges": 1,
            "external_id_mappings": 1,
            "discovery_jobs": 1,
            "recommendation_sessions": 1,
            "removed_user_seeds": 1,
            "music_entities": 2,
        }
        assert repositories.users.get(account_id="cleanup-account") is not None
    finally:
        database.close()
