create extension if not exists pgcrypto with schema extensions;

create type public.beta_access_status as enum ('pending', 'approved', 'revoked');
create type public.music_entity_type as enum ('artist', 'recording');
create type public.discovery_job_status as enum (
    'queued',
    'running',
    'ready',
    'degraded',
    'failed'
);
create type public.source_cache_status as enum ('fresh', 'negative', 'error');
create type public.recommendation_status as enum (
    'queued',
    'ready',
    'degraded',
    'insufficient',
    'reviewed',
    'exported',
    'failed'
);
create type public.feedback_event_type as enum (
    'like',
    'dislike',
    'hide_artist',
    'save',
    'skip'
);
create type public.playlist_export_status as enum (
    'creating',
    'adding_items',
    'complete',
    'partial_failure',
    'failed'
);
create type public.session_comparison as enum ('better', 'same', 'worse', 'not_sure');

create table public.app_users (
    account_id text primary key,
    display_name text,
    access_status public.beta_access_status not null default 'pending',
    refresh_token_ciphertext bytea,
    token_scopes text[] not null default '{}',
    token_issued_at timestamp with time zone,
    reauthorization_required boolean not null default false,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    deleted_at timestamp with time zone,
    version bigint not null default 1,
    constraint app_users_account_id_length check (length(account_id) between 1 and 255),
    constraint app_users_display_name_length check (
        display_name is null or length(display_name) <= 200
    ),
    constraint app_users_version_positive check (version > 0),
    constraint app_users_approved_not_deleted check (
        access_status <> 'approved' or deleted_at is null
    )
);

create index app_users_approved_active_idx
    on public.app_users (updated_at, account_id)
    where access_status = 'approved' and deleted_at is null;

create table public.oauth_states (
    state_hash text primary key,
    verifier_ciphertext bytea not null,
    return_path text not null,
    expires_at timestamp with time zone not null,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone not null default now(),
    constraint oauth_states_hash_sha256 check (state_hash ~ '^[0-9a-f]{64}$'),
    constraint oauth_states_return_path check (
        return_path like '/%'
        and return_path not like '//%'
        and length(return_path) <= 2048
    ),
    constraint oauth_states_expiry_after_creation check (expires_at > created_at)
);

create index oauth_states_expiry_idx on public.oauth_states (expires_at);

create table public.app_sessions (
    session_hash text primary key,
    account_id text not null references public.app_users (account_id) on delete cascade,
    csrf_hash text not null,
    idle_expires_at timestamp with time zone not null,
    absolute_expires_at timestamp with time zone not null,
    last_seen_at timestamp with time zone not null default now(),
    revoked_at timestamp with time zone,
    created_at timestamp with time zone not null default now(),
    constraint app_sessions_hash_sha256 check (session_hash ~ '^[0-9a-f]{64}$'),
    constraint app_sessions_csrf_hash_sha256 check (csrf_hash ~ '^[0-9a-f]{64}$'),
    constraint app_sessions_idle_before_absolute check (idle_expires_at <= absolute_expires_at),
    constraint app_sessions_absolute_after_creation check (absolute_expires_at > created_at)
);

create index app_sessions_account_idx on public.app_sessions (account_id, created_at desc);
create index app_sessions_expiry_idx
    on public.app_sessions (least(idle_expires_at, absolute_expires_at));

create table public.music_entities (
    mbid uuid primary key,
    entity_type public.music_entity_type not null,
    name text not null,
    artist_credit jsonb not null default '[]'::jsonb,
    release_data jsonb not null default '{}'::jsonb,
    isrcs text[] not null default '{}',
    source text not null default 'musicbrainz',
    source_version text,
    fetched_at timestamp with time zone not null,
    expires_at timestamp with time zone not null,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint music_entities_name_length check (length(name) between 1 and 500),
    constraint music_entities_source check (source in ('musicbrainz', 'listenbrainz')),
    constraint music_entities_artist_credit_size check (pg_column_size(artist_credit) <= 65536),
    constraint music_entities_release_data_size check (pg_column_size(release_data) <= 65536),
    constraint music_entities_expiry_after_fetch check (expires_at > fetched_at),
    unique (mbid, entity_type)
);

create index music_entities_expiry_idx on public.music_entities (expires_at);
create index music_entities_name_idx on public.music_entities (lower(name), entity_type);

create table public.user_seeds (
    id uuid primary key default gen_random_uuid(),
    account_id text not null references public.app_users (account_id) on delete cascade,
    entity_type public.music_entity_type not null,
    mbid uuid not null,
    display_name text not null,
    position smallint not null,
    selected_at timestamp with time zone not null default now(),
    removed_at timestamp with time zone,
    constraint user_seeds_entity_fk
        foreign key (mbid, entity_type)
        references public.music_entities (mbid, entity_type)
        on delete restrict,
    constraint user_seeds_display_name_length check (length(display_name) between 1 and 500),
    constraint user_seeds_position_positive check (position > 0)
);

create unique index user_seeds_active_unique_idx
    on public.user_seeds (account_id, entity_type, mbid)
    where removed_at is null;
create index user_seeds_account_position_idx
    on public.user_seeds (account_id, position)
    where removed_at is null;

create table public.discovery_jobs (
    id uuid primary key default gen_random_uuid(),
    account_id text not null references public.app_users (account_id) on delete cascade,
    request_fingerprint text not null,
    status public.discovery_job_status not null default 'queued',
    source_adapters text[] not null default '{}',
    attempt_count integer not null default 0,
    error_code text,
    queued_at timestamp with time zone not null default now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    constraint discovery_jobs_fingerprint_sha256 check (
        request_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    constraint discovery_jobs_attempt_nonnegative check (attempt_count >= 0),
    constraint discovery_jobs_error_code_length check (
        error_code is null or length(error_code) <= 100
    )
);

create unique index discovery_jobs_active_fingerprint_idx
    on public.discovery_jobs (account_id, request_fingerprint)
    where status in ('queued', 'running');
create index discovery_jobs_account_created_idx
    on public.discovery_jobs (account_id, queued_at desc);

create table public.candidate_edges (
    seed_mbid uuid not null references public.music_entities (mbid) on delete restrict,
    candidate_recording_mbid uuid not null
        references public.music_entities (mbid) on delete restrict,
    source_adapter text not null,
    algorithm_version text not null,
    strength numeric(12, 6),
    listener_count bigint,
    source_facts jsonb not null default '{}'::jsonb,
    fetched_at timestamp with time zone not null,
    expires_at timestamp with time zone not null,
    created_at timestamp with time zone not null default now(),
    primary key (seed_mbid, candidate_recording_mbid, source_adapter, algorithm_version),
    constraint candidate_edges_source_adapter check (
        source_adapter in (
            'listenbrainz_artist_radio',
            'listenbrainz_tag_radio',
            'listenbrainz_labs_similarity'
        )
    ),
    constraint candidate_edges_distinct_recordings check (
        seed_mbid <> candidate_recording_mbid
    ),
    constraint candidate_edges_strength_range check (
        strength is null or strength between 0 and 1
    ),
    constraint candidate_edges_listener_count_nonnegative check (
        listener_count is null or listener_count >= 0
    ),
    constraint candidate_edges_source_facts_size check (
        pg_column_size(source_facts) <= 65536
    ),
    constraint candidate_edges_expiry_after_fetch check (expires_at > fetched_at)
);

create index candidate_edges_seed_expiry_idx
    on public.candidate_edges (seed_mbid, expires_at);
create index candidate_edges_candidate_idx
    on public.candidate_edges (candidate_recording_mbid);

create table public.external_id_mappings (
    recording_mbid uuid not null references public.music_entities (mbid) on delete cascade,
    provider text not null,
    provider_id text not null,
    mapping_source text not null,
    confidence numeric(5, 4),
    fetched_at timestamp with time zone not null,
    expires_at timestamp with time zone not null,
    primary key (recording_mbid, provider),
    constraint external_id_mappings_provider check (provider = 'spotify'),
    constraint external_id_mappings_provider_id_length check (
        length(provider_id) between 1 and 255
    ),
    constraint external_id_mappings_confidence_range check (
        confidence is null or confidence between 0 and 1
    ),
    constraint external_id_mappings_expiry_after_fetch check (expires_at > fetched_at),
    constraint external_id_mappings_spotify_ttl check (
        provider <> 'spotify' or expires_at <= fetched_at + interval '24 hours'
    )
);

create index external_id_mappings_expiry_idx
    on public.external_id_mappings (expires_at);

create table public.source_cache_entries (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    cache_key text not null,
    status public.source_cache_status not null,
    normalized_payload jsonb not null default '{}'::jsonb,
    etag text,
    fetched_at timestamp with time zone not null,
    expires_at timestamp with time zone not null,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint source_cache_entries_source check (
        source in ('musicbrainz', 'listenbrainz', 'listenbrainz_labs')
    ),
    constraint source_cache_entries_key_length check (length(cache_key) between 1 and 1000),
    constraint source_cache_entries_payload_size check (
        pg_column_size(normalized_payload) <= 262144
    ),
    constraint source_cache_entries_expiry_after_fetch check (expires_at > fetched_at),
    unique (source, cache_key)
);

create index source_cache_entries_expiry_idx on public.source_cache_entries (expires_at);

create table public.source_rate_limits (
    source text primary key,
    next_allowed_at timestamp with time zone not null,
    updated_at timestamp with time zone not null default now(),
    constraint source_rate_limits_source check (
        source in ('musicbrainz', 'listenbrainz', 'listenbrainz_labs')
    )
);

create table public.user_preferences (
    account_id text primary key references public.app_users (account_id) on delete cascade,
    blocked_artist_mbids uuid[] not null default '{}',
    blocked_recording_mbids uuid[] not null default '{}',
    allow_explicit boolean not null default false,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now()
);

create table public.recommendation_sessions (
    id uuid primary key default gen_random_uuid(),
    account_id text not null references public.app_users (account_id) on delete cascade,
    prompt text not null,
    controls jsonb not null default '{}'::jsonb,
    parsed_intent jsonb not null default '{}'::jsonb,
    seed_ids uuid[] not null,
    source_snapshot jsonb not null default '{}'::jsonb,
    ranking_version text not null,
    status public.recommendation_status not null default 'queued',
    generated_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    reviewed_playlist_name text,
    reviewed_playlist_public boolean,
    constraint recommendation_sessions_prompt_length check (length(prompt) between 1 and 1000),
    constraint recommendation_sessions_controls_size check (pg_column_size(controls) <= 32768),
    constraint recommendation_sessions_intent_size check (pg_column_size(parsed_intent) <= 32768),
    constraint recommendation_sessions_seed_count check (cardinality(seed_ids) between 1 and 5),
    constraint recommendation_sessions_source_snapshot_size check (
        pg_column_size(source_snapshot) <= 131072
    ),
    constraint recommendation_sessions_ranking_version_length check (
        length(ranking_version) between 1 and 100
    ),
    constraint recommendation_sessions_playlist_name_length check (
        reviewed_playlist_name is null or length(reviewed_playlist_name) between 1 and 100
    ),
    unique (id, account_id)
);

create index recommendation_sessions_account_created_idx
    on public.recommendation_sessions (account_id, generated_at desc);

create table public.recommendation_items (
    session_id uuid not null references public.recommendation_sessions (id) on delete cascade,
    recording_mbid uuid not null references public.music_entities (mbid) on delete restrict,
    spotify_track_id text,
    original_rank smallint not null,
    internal_score_components jsonb not null,
    evidence jsonb not null,
    display_snapshot jsonb not null,
    selected boolean not null default true,
    reviewed_order smallint,
    created_at timestamp with time zone not null default now(),
    primary key (session_id, recording_mbid),
    constraint recommendation_items_original_rank_positive check (original_rank > 0),
    constraint recommendation_items_reviewed_order_positive check (
        reviewed_order is null or reviewed_order > 0
    ),
    constraint recommendation_items_score_size check (
        pg_column_size(internal_score_components) <= 32768
    ),
    constraint recommendation_items_evidence_size check (pg_column_size(evidence) <= 65536),
    constraint recommendation_items_display_size check (
        pg_column_size(display_snapshot) <= 65536
    ),
    unique (session_id, original_rank)
);

create unique index recommendation_items_reviewed_order_idx
    on public.recommendation_items (session_id, reviewed_order)
    where reviewed_order is not null;

create table public.feedback_events (
    id uuid primary key default gen_random_uuid(),
    account_id text not null,
    session_id uuid not null,
    recording_mbid uuid not null,
    event_type public.feedback_event_type not null,
    metadata jsonb not null default '{}'::jsonb,
    idempotency_key text not null,
    created_at timestamp with time zone not null default now(),
    constraint feedback_events_session_owner_fk
        foreign key (session_id, account_id)
        references public.recommendation_sessions (id, account_id)
        on delete cascade,
    constraint feedback_events_item_fk
        foreign key (session_id, recording_mbid)
        references public.recommendation_items (session_id, recording_mbid)
        on delete cascade,
    constraint feedback_events_metadata_size check (pg_column_size(metadata) <= 16384),
    constraint feedback_events_idempotency_key_length check (
        length(idempotency_key) between 1 and 255
    ),
    unique (account_id, idempotency_key)
);

create index feedback_events_session_created_idx
    on public.feedback_events (session_id, created_at);

create table public.playlist_exports (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique,
    account_id text not null,
    spotify_playlist_id text,
    spotify_playlist_url text,
    name text not null,
    description text not null default '',
    public boolean not null default false,
    recording_mbids uuid[] not null,
    spotify_track_ids text[] not null,
    request_fingerprint text not null,
    idempotency_key text not null,
    status public.playlist_export_status not null default 'creating',
    tracks_added smallint not null default 0,
    partial_failure jsonb,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint playlist_exports_session_owner_fk
        foreign key (session_id, account_id)
        references public.recommendation_sessions (id, account_id)
        on delete cascade,
    constraint playlist_exports_name_length check (length(name) between 1 and 100),
    constraint playlist_exports_description_length check (length(description) <= 300),
    constraint playlist_exports_track_count check (
        cardinality(recording_mbids) between 1 and 20
        and cardinality(recording_mbids) = cardinality(spotify_track_ids)
    ),
    constraint playlist_exports_request_fingerprint_sha256 check (
        request_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    constraint playlist_exports_idempotency_key_length check (
        length(idempotency_key) between 1 and 255
    ),
    constraint playlist_exports_tracks_added_range check (
        tracks_added between 0 and 20
    ),
    constraint playlist_exports_partial_failure_size check (
        partial_failure is null or pg_column_size(partial_failure) <= 16384
    ),
    unique (account_id, idempotency_key)
);

create table public.session_evaluations (
    session_id uuid primary key,
    account_id text not null,
    comparison public.session_comparison not null,
    explanation_usefulness smallint not null,
    novelty_quality smallint not null,
    comment text,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    constraint session_evaluations_session_owner_fk
        foreign key (session_id, account_id)
        references public.recommendation_sessions (id, account_id)
        on delete cascade,
    constraint session_evaluations_explanation_range check (
        explanation_usefulness between 1 and 5
    ),
    constraint session_evaluations_novelty_range check (novelty_quality between 1 and 5),
    constraint session_evaluations_comment_length check (
        comment is null or length(comment) <= 1000
    )
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger app_users_set_updated_at
before update on public.app_users
for each row execute function public.set_updated_at();

create trigger music_entities_set_updated_at
before update on public.music_entities
for each row execute function public.set_updated_at();

create trigger source_cache_entries_set_updated_at
before update on public.source_cache_entries
for each row execute function public.set_updated_at();

create trigger source_rate_limits_set_updated_at
before update on public.source_rate_limits
for each row execute function public.set_updated_at();

create trigger user_preferences_set_updated_at
before update on public.user_preferences
for each row execute function public.set_updated_at();

create trigger recommendation_sessions_set_updated_at
before update on public.recommendation_sessions
for each row execute function public.set_updated_at();

create trigger playlist_exports_set_updated_at
before update on public.playlist_exports
for each row execute function public.set_updated_at();

create trigger session_evaluations_set_updated_at
before update on public.session_evaluations
for each row execute function public.set_updated_at();

create or replace function public.enforce_beta_approved_limit()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    becoming_approved boolean;
    approved_count integer;
begin
    if tg_op = 'INSERT' then
        becoming_approved := new.access_status = 'approved' and new.deleted_at is null;
    else
        becoming_approved := new.access_status = 'approved'
            and new.deleted_at is null
            and (
                old.access_status is distinct from new.access_status
                or old.deleted_at is distinct from new.deleted_at
            );
    end if;

    if not becoming_approved then
        return new;
    end if;

    perform pg_advisory_xact_lock(hashtextextended('outside-the-loop-approved-users', 0));

    select count(*)
    into approved_count
    from public.app_users
    where access_status = 'approved'
      and deleted_at is null
      and account_id <> new.account_id;

    if approved_count >= 5 then
        raise exception 'Outside the Loop beta permits at most five approved users.'
            using errcode = '23514';
    end if;

    return new;
end;
$$;

create trigger app_users_enforce_beta_approved_limit
before insert or update of access_status, deleted_at on public.app_users
for each row execute function public.enforce_beta_approved_limit();

create or replace function public.enforce_active_seed_limit()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    becoming_active boolean;
    active_count integer;
begin
    if tg_op = 'INSERT' then
        becoming_active := new.removed_at is null;
    else
        becoming_active := new.removed_at is null
            and (
                old.removed_at is distinct from new.removed_at
                or old.account_id is distinct from new.account_id
            );
    end if;

    if not becoming_active then
        return new;
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('outside-the-loop-seeds:' || new.account_id, 0)
    );

    select count(*)
    into active_count
    from public.user_seeds
    where account_id = new.account_id
      and removed_at is null
      and id <> new.id;

    if active_count >= 5 then
        raise exception 'Outside the Loop permits at most five active seeds per account.'
            using errcode = '23514';
    end if;

    return new;
end;
$$;

create trigger user_seeds_enforce_active_limit
before insert or update of account_id, removed_at on public.user_seeds
for each row execute function public.enforce_active_seed_limit();

create or replace function public.consume_oauth_state(
    p_state_hash text,
    p_now timestamp with time zone default now()
)
returns setof public.oauth_states
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    return query
    update public.oauth_states
    set consumed_at = p_now
    where state_hash = p_state_hash
      and consumed_at is null
      and expires_at > p_now
    returning *;
end;
$$;

alter table public.app_users enable row level security;
alter table public.oauth_states enable row level security;
alter table public.app_sessions enable row level security;
alter table public.music_entities enable row level security;
alter table public.user_seeds enable row level security;
alter table public.discovery_jobs enable row level security;
alter table public.candidate_edges enable row level security;
alter table public.external_id_mappings enable row level security;
alter table public.source_cache_entries enable row level security;
alter table public.source_rate_limits enable row level security;
alter table public.user_preferences enable row level security;
alter table public.recommendation_sessions enable row level security;
alter table public.recommendation_items enable row level security;
alter table public.feedback_events enable row level security;
alter table public.playlist_exports enable row level security;
alter table public.session_evaluations enable row level security;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on function public.set_updated_at() from public, anon, authenticated;
revoke all on function public.enforce_beta_approved_limit() from public, anon, authenticated;
revoke all on function public.enforce_active_seed_limit() from public, anon, authenticated;
revoke all on function public.consume_oauth_state(text, timestamp with time zone)
    from public, anon, authenticated;

alter default privileges in schema public
    revoke all on tables from anon, authenticated;
alter default privileges in schema public
    revoke all on sequences from anon, authenticated;
alter default privileges in schema public
    revoke execute on functions from public, anon, authenticated;
