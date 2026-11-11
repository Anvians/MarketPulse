-- MarketPulse master schema script (psql only; uses \i includes).
-- Order matters: tables -> (load data with the Python pipeline) -> relationships -> indexes -> views.
--
-- Typical manual use:
--   psql -U postgres -d postgres  -f database/create_database.sql
--   psql -U postgres -d marketpulse -f database/create_tables.sql
--   python -m ingestion.run_pipeline --load-only      (or the full pipeline)
--   psql -U postgres -d marketpulse -f database/create_relationships.sql
--   psql -U postgres -d marketpulse -f database/create_indexes.sql
--   psql -U postgres -d marketpulse -f database/analytical_views.sql
--
-- The pipeline `python -m ingestion.run_pipeline` runs all of the above for you.

\i database/create_tables.sql
\echo 'Tables created. Load data now (python -m ingestion.run_pipeline), then run:'
\echo '  \\i database/create_relationships.sql'
\echo '  \\i database/create_indexes.sql'
\echo '  \\i database/analytical_views.sql'
