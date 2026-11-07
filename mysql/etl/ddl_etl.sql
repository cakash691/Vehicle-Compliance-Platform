-- =====================================================================================
-- ddl_etl.sql -- the run log and watermarks, in the etl database
-- Run once, after 00_setup_mysql.sql:
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/etl/ddl_etl.sql
-- Safe to run again: it never drops or empties a table.
-- =====================================================================================

-- one row per run of run_pipeline.py
CREATE TABLE IF NOT EXISTS etl.batch (
  batch_id     INT          NOT NULL AUTO_INCREMENT,
  as_of        DATE         NOT NULL,          -- business date: the last day this run covers
  started_at   DATETIME     NOT NULL,
  finished_at  DATETIME     NULL,
  status       VARCHAR(10)  NOT NULL,          -- RUNNING | SUCCESS | FAILED
  message      VARCHAR(500) NULL,              -- the error, when status = FAILED
  PRIMARY KEY (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- one row per step of a run (later also one per quality check)
CREATE TABLE IF NOT EXISTS etl.step_log (
  step_id        INT          NOT NULL AUTO_INCREMENT,
  batch_id       INT          NOT NULL,
  step           VARCHAR(100) NOT NULL,        -- e.g. bronze.capture_log
  rows_affected  INT          NULL,
  status         VARCHAR(12)  NOT NULL,        -- RUNNING | OK | FAILED | ROLLED_BACK (undone by a later failure)
  started_at     DATETIME     NOT NULL,
  finished_at    DATETIME     NULL,
  PRIMARY KEY (step_id),
  KEY idx_batch_id (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- one row per source table: how far bronze has copied it
CREATE TABLE IF NOT EXISTS etl.watermark (
  source_table      VARCHAR(64)  NOT NULL,     -- e.g. roadcapture.capture_log
  watermark_column  VARCHAR(64)  NOT NULL,     -- e.g. ingested_at
  watermark_value   VARCHAR(19)  NOT NULL,     -- newest value copied: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
  batch_id          INT          NOT NULL,     -- batch that last moved it
  PRIMARY KEY (source_table)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
