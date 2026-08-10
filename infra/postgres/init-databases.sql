-- Runs once on a brand-new Postgres data volume.
-- Creates one database per service so cross-service foreign keys are impossible.
CREATE DATABASE gateway_service;
