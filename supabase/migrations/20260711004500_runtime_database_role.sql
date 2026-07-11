do $$
begin
    if not exists (
        select 1 from pg_roles where rolname = 'outside_loop_runtime'
    ) then
        create role outside_loop_runtime;
    end if;
end;
$$;

do $$
begin
    if exists (
        select 1
        from pg_roles
        where rolname = 'outside_loop_runtime'
          and (rolsuper or rolreplication)
    ) then
        raise exception 'outside_loop_runtime must not be a superuser or replication role';
    end if;
end;
$$;

alter role outside_loop_runtime
    with nologin
    nocreatedb
    nocreaterole
    noinherit
    bypassrls
    connection limit 24;

revoke all privileges on database postgres from outside_loop_runtime;
grant connect on database postgres to outside_loop_runtime;

revoke all privileges on schema public from outside_loop_runtime;
grant usage on schema public to outside_loop_runtime;

revoke all privileges on all tables in schema public from outside_loop_runtime;
grant select, insert, update, delete on all tables in schema public
    to outside_loop_runtime;

revoke all privileges on all sequences in schema public from outside_loop_runtime;
grant usage, select on all sequences in schema public to outside_loop_runtime;

grant execute on function public.consume_oauth_state(text, timestamp with time zone)
    to outside_loop_runtime;

alter default privileges in schema public
    grant select, insert, update, delete on tables to outside_loop_runtime;
alter default privileges in schema public
    grant usage, select on sequences to outside_loop_runtime;
