-- Development bootstrap. Production provisions these roles through its own
-- infrastructure pipeline, but the privilege model must be identical: the
-- runtime role is NOT the owner and does NOT have BYPASSRLS.
--
-- app_migrator  owns the schema, runs Alembic. Not used at runtime.
-- app_runtime   the API and workers. RLS applies. No DDL, no BYPASSRLS.
-- app_platform  cross-tenant work (platform admin, analytics jobs). BYPASSRLS.

\set app_password       `echo "'$APP_PASSWORD'"`
\set migrator_password  `echo "'$MIGRATOR_PASSWORD'"`
\set platform_password  `echo "'$PLATFORM_PASSWORD'"`
\set keycloak_password  `echo "'$KEYCLOAK_DB_PASSWORD'"`

CREATE ROLE app_migrator LOGIN PASSWORD :migrator_password;
CREATE ROLE app_runtime  LOGIN PASSWORD :app_password;
CREATE ROLE app_platform LOGIN PASSWORD :platform_password BYPASSRLS;

-- Keycloak gets its own database and role: it is a separate system and must
-- never be able to read application tables.
CREATE ROLE keycloak LOGIN PASSWORD :keycloak_password;
CREATE DATABASE keycloak OWNER keycloak;

\connect footbola

-- The migrator owns the schema; nobody else may create objects.
ALTER SCHEMA public OWNER TO app_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_runtime, app_platform;

-- Runtime roles get DML only, on both existing and future objects.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO app_runtime, app_platform;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO app_runtime, app_platform;

ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime, app_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_runtime, app_platform;

-- Extensions used by the schema.
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
