begin;

create extension if not exists pgtap with schema extensions;

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
restart identity cascade;

select no_plan();

select has_table('public', 'app_users', 'app_users table exists');
select has_table('public', 'oauth_states', 'oauth_states table exists');
select has_table('public', 'app_sessions', 'app_sessions table exists');
select has_table('public', 'user_seeds', 'user_seeds table exists');
select has_table('public', 'discovery_jobs', 'discovery_jobs table exists');
select has_table('public', 'music_entities', 'music_entities table exists');
select has_table('public', 'candidate_edges', 'candidate_edges table exists');
select has_table(
    'public',
    'external_id_mappings',
    'external_id_mappings table exists'
);
select has_table('public', 'source_cache_entries', 'source_cache_entries table exists');
select has_table('public', 'source_rate_limits', 'source_rate_limits table exists');
select has_table('public', 'user_preferences', 'user_preferences table exists');
select has_table(
    'public',
    'recommendation_sessions',
    'recommendation_sessions table exists'
);
select has_table('public', 'recommendation_items', 'recommendation_items table exists');
select has_table('public', 'feedback_events', 'feedback_events table exists');
select has_table('public', 'playlist_exports', 'playlist_exports table exists');
select has_table('public', 'session_evaluations', 'session_evaluations table exists');

select has_function('public', 'consume_oauth_state', array['text', 'timestamp with time zone']);
select has_index(
    'public',
    'app_users',
    'app_users_approved_active_idx',
    'approved-user scheduler index exists'
);

select ok(
    (
        select jsonb_agg(enumlabel order by enumsortorder)
        from pg_enum
        where enumtypid = 'public.recommendation_status'::regtype
    ) = '["queued", "ready", "degraded", "insufficient", "reviewed", "exported", "failed"]'::jsonb,
    'recommendation status captures honest coverage states'
);
select has_index(
    'public',
    'user_seeds',
    'user_seeds_active_unique_idx',
    'active seed uniqueness index exists'
);
select has_index(
    'public',
    'discovery_jobs',
    'discovery_jobs_active_fingerprint_idx',
    'active discovery idempotency index exists'
);
select has_index(
    'public',
    'recommendation_sessions',
    'recommendation_sessions_account_created_idx',
    'account history index exists'
);

select results_eq(
    $$
    select count(*)::bigint
    from pg_class
    where oid in (
        'public.app_users'::regclass,
        'public.oauth_states'::regclass,
        'public.app_sessions'::regclass,
        'public.user_seeds'::regclass,
        'public.discovery_jobs'::regclass,
        'public.music_entities'::regclass,
        'public.candidate_edges'::regclass,
        'public.external_id_mappings'::regclass,
        'public.source_cache_entries'::regclass,
        'public.source_rate_limits'::regclass,
        'public.user_preferences'::regclass,
        'public.recommendation_sessions'::regclass,
        'public.recommendation_items'::regclass,
        'public.feedback_events'::regclass,
        'public.playlist_exports'::regclass,
        'public.session_evaluations'::regclass
    )
      and relrowsecurity
    $$,
    array[16::bigint],
    'all product tables have row-level security enabled'
);

select results_eq(
    $$
    select count(*)::bigint
    from information_schema.role_table_grants
    where table_schema = 'public'
      and grantee in ('anon', 'authenticated')
      and table_name in (
          'app_users',
          'oauth_states',
          'app_sessions',
          'user_seeds',
          'discovery_jobs',
          'music_entities',
          'candidate_edges',
          'external_id_mappings',
          'source_cache_entries',
          'source_rate_limits',
          'user_preferences',
          'recommendation_sessions',
          'recommendation_items',
          'feedback_events',
          'playlist_exports',
          'session_evaluations'
      )
    $$,
    array[0::bigint],
    'browser database roles have no direct table grants'
);

select ok(
    exists (
        select 1
        from pg_roles
        where rolname = 'outside_loop_runtime'
          and not rolcanlogin
          and not rolsuper
          and not rolcreatedb
          and not rolcreaterole
          and not rolreplication
          and rolbypassrls
    ),
    'runtime role is non-login, non-administrative, and can enforce backend ownership'
);

select results_eq(
    $$
    select count(*)::bigint
    from (
        select table_name
        from information_schema.role_table_grants
        where table_schema = 'public'
          and grantee = 'outside_loop_runtime'
          and privilege_type in ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
        group by table_name
        having count(distinct privilege_type) = 4
    ) granted_tables
    $$,
    array[16::bigint],
    'runtime role has DML but no ownership privileges on every product table'
);

select ok(
    case
        when exists (select 1 from pg_roles where rolname = 'outside_loop_runtime') then
            has_schema_privilege('outside_loop_runtime', 'public', 'USAGE')
            and not has_schema_privilege('outside_loop_runtime', 'public', 'CREATE')
            and has_function_privilege(
                'outside_loop_runtime',
                'public.consume_oauth_state(text, timestamp with time zone)',
                'EXECUTE'
            )
        else false
    end,
    'runtime role can use product schema and OAuth function but cannot create objects'
);

select ok(
    case
        when exists (select 1 from pg_roles where rolname = 'outside_loop_runtime') then
            has_schema_privilege('outside_loop_runtime', 'supabase_migrations', 'USAGE')
            and has_table_privilege(
                'outside_loop_runtime',
                'supabase_migrations.schema_migrations',
                'SELECT'
            )
            and not has_table_privilege(
                'outside_loop_runtime',
                'supabase_migrations.schema_migrations',
                'INSERT,UPDATE,DELETE'
            )
        else false
    end,
    'runtime role can read migration versions but cannot modify migration history'
);

insert into public.app_users (account_id, access_status)
values
    ('account-1', 'approved'),
    ('account-2', 'approved'),
    ('account-3', 'approved'),
    ('account-4', 'approved'),
    ('account-5', 'approved');

select throws_ok(
    $$
    insert into public.app_users (account_id, access_status)
    values ('account-6', 'approved')
    $$,
    '23514',
    'Outside the Loop beta permits at most five approved users.',
    'database rejects a sixth approved beta account'
);

insert into public.oauth_states (
    state_hash,
    verifier_ciphertext,
    return_path,
    expires_at
)
values (
    repeat('a', 64),
    decode('74657374', 'hex'),
    '/discover',
    '2030-01-01T00:10:00Z'
);

select results_eq(
    $$
    select count(*)::bigint
    from public.consume_oauth_state(repeat('a', 64), '2030-01-01T00:00:00Z')
    $$,
    array[1::bigint],
    'an unexpired OAuth state is consumed once'
);

select results_eq(
    $$
    select count(*)::bigint
    from public.consume_oauth_state(repeat('a', 64), '2030-01-01T00:00:01Z')
    $$,
    array[0::bigint],
    'an OAuth state replay returns no record'
);

insert into public.music_entities (mbid, entity_type, name, fetched_at, expires_at)
values
    ('10000000-0000-0000-0000-000000000001', 'artist', 'Seed 1', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z'),
    ('10000000-0000-0000-0000-000000000002', 'artist', 'Seed 2', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z'),
    ('10000000-0000-0000-0000-000000000003', 'artist', 'Seed 3', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z'),
    ('10000000-0000-0000-0000-000000000004', 'artist', 'Seed 4', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z'),
    ('10000000-0000-0000-0000-000000000005', 'artist', 'Seed 5', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z'),
    ('10000000-0000-0000-0000-000000000006', 'artist', 'Seed 6', '2030-01-01T00:00:00Z', '2030-01-31T00:00:00Z');

insert into public.user_seeds (id, account_id, entity_type, mbid, display_name, position)
values
    ('00000000-0000-0000-0000-000000000001', 'account-1', 'artist', '10000000-0000-0000-0000-000000000001', 'Seed 1', 1),
    ('00000000-0000-0000-0000-000000000002', 'account-1', 'artist', '10000000-0000-0000-0000-000000000002', 'Seed 2', 2),
    ('00000000-0000-0000-0000-000000000003', 'account-1', 'artist', '10000000-0000-0000-0000-000000000003', 'Seed 3', 3),
    ('00000000-0000-0000-0000-000000000004', 'account-1', 'artist', '10000000-0000-0000-0000-000000000004', 'Seed 4', 4),
    ('00000000-0000-0000-0000-000000000005', 'account-1', 'artist', '10000000-0000-0000-0000-000000000005', 'Seed 5', 5);

select throws_ok(
    $$
    insert into public.user_seeds (account_id, entity_type, mbid, display_name, position)
    values ('account-1', 'artist', '10000000-0000-0000-0000-000000000006', 'Seed 6', 6)
    $$,
    '23514',
    'Outside the Loop permits at most five active seeds per account.',
    'database rejects a sixth active seed for one account'
);

select * from finish();

rollback;
