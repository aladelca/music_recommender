from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3

from music_recommender.auth.oauth import OAuthService, ProductAuthService
from music_recommender.auth.sessions import CsrfProtection, SessionService
from music_recommender.config import Settings, load_settings
from music_recommender.observability import ProductObserver
from music_recommender.product.account_service import AccountService
from music_recommender.product.discovery_queue import SqsDiscoveryPublisher
from music_recommender.product.discovery_service import (
    DiscoveryJobService,
    DiscoveryQueuePublisher,
)
from music_recommender.product.feedback_service import FeedbackEvaluationService
from music_recommender.product.playlist_export_service import PlaylistExportService
from music_recommender.product.recommendation_service import RecommendationService
from music_recommender.product.seed_service import SeedService
from music_recommender.product.spotify_account import AccountSpotifyClientFactory
from music_recommender.security.token_vault import KmsTokenVault
from music_recommender.sources.musicbrainz import MusicBrainzClient
from music_recommender.sources.spotify_user import SpotifyUserClient
from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings
from music_recommender.storage.postgres_repositories import PostgresRepositories

_ALLOWED_RETURN_PATHS = (
    "/discover",
    "/onboarding",
    "/history",
    "/settings",
)


@dataclass(frozen=True)
class ProductAuthRuntime:
    auth_service: ProductAuthService
    session_service: SessionService
    csrf_protection: CsrfProtection
    database: PostgresDatabase
    seed_service: SeedService
    discovery_job_service: DiscoveryJobService | None
    recommendation_service: RecommendationService
    playlist_export_service: PlaylistExportService
    feedback_evaluation_service: FeedbackEvaluationService
    account_service: AccountService
    observer: ProductObserver

    def ready(self) -> bool:
        with self.database.system_transaction() as connection:
            row = connection.execute("select 1 as ready").fetchone()
        return bool(row and row.get("ready") == 1)


def build_product_auth_runtime(
    settings: Settings | None = None,
    *,
    database: PostgresDatabase | None = None,
    token_vault: Any | None = None,
    discovery_publisher: DiscoveryQueuePublisher | None = None,
) -> ProductAuthRuntime:
    resolved_settings = settings or load_settings()
    if resolved_settings.auth_mode == "api_key":
        raise ValueError("Product auth runtime requires AUTH_MODE=hybrid or spotify_session.")
    resolved_database = database or PostgresDatabase(
        PostgresPoolSettings.from_settings(resolved_settings)
    )
    repositories = PostgresRepositories(resolved_database)
    if resolved_settings.observability_hash_key is None:
        raise ValueError("OBSERVABILITY_HASH_KEY is required for the product runtime.")
    observer = ProductObserver(
        service="product-api",
        hash_key=resolved_settings.observability_hash_key,
    )
    resolved_vault = token_vault or KmsTokenVault.from_settings(resolved_settings)
    if resolved_settings.musicbrainz_contact_email is None:
        raise ValueError("MUSICBRAINZ_CONTACT_EMAIL is required for product discovery.")
    musicbrainz = MusicBrainzClient(
        contact_email=resolved_settings.musicbrainz_contact_email,
        app_version="0.1.0",
    )
    oauth = OAuthService(
        client_id=resolved_settings.spotify_client_id,
        redirect_uri=resolved_settings.spotify_redirect_uri,
        scopes=resolved_settings.spotify_product_scopes,
        state_repository=repositories.oauth_states,
        verifier_vault=resolved_vault,
        allowed_return_paths=_ALLOWED_RETURN_PATHS,
    )
    sessions = SessionService(repository=repositories.sessions)
    auth_service = ProductAuthService(
        oauth=oauth,
        sessions=sessions,
        users=repositories.users,
        seeds=repositories.seeds,
        token_vault=resolved_vault,
        spotify_client_factory=lambda: SpotifyUserClient(
            client_id=resolved_settings.spotify_client_id,
            client_secret=resolved_settings.spotify_client_secret,
        ),
    )
    seed_service = SeedService(
        musicbrainz=musicbrainz,
        cache=repositories.source_cache,
        entities=repositories.music_entities,
        seeds=repositories.seeds,
        rate_limiter=repositories.source_rate_limits,
    )
    resolved_publisher = discovery_publisher
    if resolved_publisher is None and resolved_settings.discovery_queue_url is not None:
        resolved_publisher = SqsDiscoveryPublisher(
            queue_url=resolved_settings.discovery_queue_url,
            sqs_client=boto3.client("sqs", region_name=resolved_settings.aws_region),
        )
    discovery_job_service = (
        DiscoveryJobService(
            jobs=repositories.discovery_jobs,
            seeds=repositories.seeds,
            publisher=resolved_publisher,
        )
        if resolved_publisher is not None
        else None
    )
    spotify_account_clients = AccountSpotifyClientFactory(
        users=repositories.users,
        token_vault=resolved_vault,
        client_id=resolved_settings.spotify_client_id,
        client_secret=resolved_settings.spotify_client_secret,
    )
    recommendation_service = RecommendationService(
        seeds=repositories.seeds,
        candidate_edges=repositories.candidate_edges,
        entities=repositories.music_entities,
        preferences=repositories.user_preferences,
        mappings=repositories.external_id_mappings,
        recommendations=repositories.recommendations,
        spotify_clients=spotify_account_clients,
        market=resolved_settings.spotify_market,
    )
    playlist_export_service = PlaylistExportService(
        recommendations=repositories.recommendations,
        exports=repositories.playlist_exports,
        spotify_clients=spotify_account_clients,
    )
    feedback_evaluation_service = FeedbackEvaluationService(
        recommendations=repositories.recommendations,
        entities=repositories.music_entities,
        feedback=repositories.feedback_events,
        preferences=repositories.user_preferences,
        evaluations=repositories.session_evaluations,
    )
    account_service = AccountService(accounts=repositories.account_deletion)
    return ProductAuthRuntime(
        auth_service=auth_service,
        session_service=sessions,
        csrf_protection=CsrfProtection(
            allowed_origins=resolved_settings.auth_allowed_origins,
        ),
        database=resolved_database,
        seed_service=seed_service,
        discovery_job_service=discovery_job_service,
        recommendation_service=recommendation_service,
        playlist_export_service=playlist_export_service,
        feedback_evaluation_service=feedback_evaluation_service,
        account_service=account_service,
        observer=observer,
    )
