revoke all privileges on schema supabase_migrations from outside_loop_runtime;
grant usage on schema supabase_migrations to outside_loop_runtime;

revoke all privileges on table supabase_migrations.schema_migrations
    from outside_loop_runtime;
grant select on table supabase_migrations.schema_migrations
    to outside_loop_runtime;
