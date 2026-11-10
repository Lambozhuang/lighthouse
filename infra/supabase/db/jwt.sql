-- Runs once, when the database volume is first initialised.
--
-- Makes the access token lifetime readable from SQL as current_setting('app.settings.jwt_exp').
-- From https://github.com/supabase/supabase/blob/master/docker/volumes/db/jwt.sql
\set jwt_exp `echo "$JWT_EXP"`

ALTER DATABASE postgres SET "app.settings.jwt_exp" TO :'jwt_exp';
