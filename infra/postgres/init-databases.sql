-- Runs once on a brand-new Postgres data volume.
-- Creates one database per service so cross-service foreign keys are impossible.
-- Postgres has already created POSTGRES_DB by the time this runs, and has no
-- CREATE DATABASE IF NOT EXISTS, so each statement is generated only for a
-- missing database and executed by psql's \gexec.
SELECT format('CREATE DATABASE %I', name)
FROM unnest(ARRAY[
    'gateway_service',
    'inventory_service',
    'order_service',
    'payment_service',
    'notification_service',
    'recommendation_service'
]) AS name
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = name)
\gexec
