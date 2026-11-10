-- Runs once, when the database volume is first initialised.
--
-- The supabase/postgres image creates its service roles without usable passwords. Give them the
-- password from the environment so Auth (supabase_auth_admin) and PostgREST (authenticator)
-- can log in. The other two belong to services this stack does not run (pooler, storage); they
-- get the same password so that no login role is left without one.
--
-- Adapted from https://github.com/supabase/supabase/blob/master/docker/volumes/db/roles.sql
-- (without supabase_functions_admin, which only exists when the webhooks script is installed).
--
-- If a script in this directory fails, initialisation stops half-way and the volume must be
-- recreated: docker compose down -v
\set pgpass `echo "$POSTGRES_PASSWORD"`

ALTER USER authenticator WITH PASSWORD :'pgpass';
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
ALTER USER pgbouncer WITH PASSWORD :'pgpass';
ALTER USER supabase_storage_admin WITH PASSWORD :'pgpass';
