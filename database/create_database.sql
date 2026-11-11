-- MarketPulse: create the analytical database.
-- Run while connected to the maintenance database, e.g.:
--   psql -U postgres -d postgres -f database/create_database.sql
-- (The Python pipeline does the same thing via config.database.ensure_database_exists.)

SELECT 'CREATE DATABASE marketpulse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marketpulse')\gexec
