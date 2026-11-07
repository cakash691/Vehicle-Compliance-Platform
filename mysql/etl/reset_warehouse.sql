-- =====================================================================================
-- reset_warehouse.sql -- empty the warehouse layers and the run log
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/etl/reset_warehouse.sql
--
-- Run it whenever you recreate the source tables (01_create_source_tables.sql) and want
-- to replay the simulated nights from scratch. Without it, run_pipeline.py stops with
-- "looks reset", because the sources are now older than the stored watermarks.
-- =====================================================================================

TRUNCATE TABLE bronze.registrations;
TRUNCATE TABLE bronze.policies;
TRUNCATE TABLE bronze.theft_shredding;
TRUNCATE TABLE bronze.capture_log;

-- silver is rebuilt from bronze on every run; emptying it keeps a reset tidy
TRUNCATE TABLE silver.plate_lookup;
TRUNCATE TABLE silver.registrations;
TRUNCATE TABLE silver.policies;
TRUNCATE TABLE silver.theft_shredding;
TRUNCATE TABLE silver.capture_log;

-- gold keeps history, so a replay starts it from empty too (the pipeline refills dim_date)
TRUNCATE TABLE gold.fact_compliance_monthly;
TRUNCATE TABLE gold.fact_theft_case;
TRUNCATE TABLE gold.fact_sighting;
TRUNCATE TABLE gold.fact_policy;
TRUNCATE TABLE gold.dim_vehicle;
TRUNCATE TABLE gold.dim_insurer;
TRUNCATE TABLE gold.dim_location;
TRUNCATE TABLE gold.dim_state;
TRUNCATE TABLE gold.dim_date;

TRUNCATE TABLE etl.watermark;
TRUNCATE TABLE etl.step_log;
TRUNCATE TABLE etl.batch;
