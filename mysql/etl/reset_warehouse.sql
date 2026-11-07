-- =====================================================================================
-- reset_warehouse.sql -- empty the warehouse layers and the run log
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/etl/reset_warehouse.sql
--
-- Run it whenever you recreate the source tables (01_create_source_tables.sql) and want
-- to replay the simulated nights from scratch. Without it, run_pipeline.py stops with
-- "looks reset", because the sources are now older than the stored watermarks.
-- Silver and gold tables get added here as those layers are built.
-- =====================================================================================

TRUNCATE TABLE bronze.registrations;
TRUNCATE TABLE bronze.policies;
TRUNCATE TABLE bronze.theft_shredding;
TRUNCATE TABLE bronze.capture_log;

TRUNCATE TABLE etl.watermark;
TRUNCATE TABLE etl.step_log;
TRUNCATE TABLE etl.batch;
