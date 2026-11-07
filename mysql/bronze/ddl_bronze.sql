-- =====================================================================================
-- ddl_bronze.sql -- bronze: append-only copies of the four source tables
-- Run once, after 00_setup_mysql.sql:
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/bronze/ddl_bronze.sql
-- Safe to run again: it never drops or empties a table (bronze is the history).
--
-- Each table has the source's columns, plus the batch that copied the row and when.
-- Columns accept NULL on purpose: bronze stores whatever the source sent, and silver
-- does the checking. The primary key is the source id plus the batch, because a source
-- row that changes (an owner transfer, a recovered theft) is copied again in a later batch.
-- =====================================================================================

-- from rto_registration.registrations (changes tracked by last_updated)
CREATE TABLE IF NOT EXISTS bronze.registrations (
  reg_id             INT          NOT NULL,
  reg_no             VARCHAR(20),
  owner_name         VARCHAR(80),
  make_model         VARCHAR(50),
  registration_date  DATE,
  maker              VARCHAR(30),
  vehicle_class      VARCHAR(40),
  body_type          VARCHAR(20),
  fuel_type          VARCHAR(20),
  colour             VARCHAR(20),
  chassis_no         CHAR(17),
  rto_code           VARCHAR(6),
  rto_name           VARCHAR(120),
  state_name         VARCHAR(60),
  transport_category VARCHAR(15),
  owner_type         VARCHAR(12),
  owner_serial       TINYINT,
  reg_valid_upto     DATE,
  reg_status         VARCHAR(12),
  last_updated       DATE,
  dwh_batch_id       INT          NOT NULL,
  dwh_loaded_at      DATETIME     NOT NULL,
  PRIMARY KEY (reg_id, dwh_batch_id),
  KEY idx_dwh_batch_id (dwh_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- from insurance.policies (new rows tracked by issued_at)
CREATE TABLE IF NOT EXISTS bronze.policies (
  policy_id       INT          NOT NULL,
  vehicle_number  VARCHAR(20),
  insurer         VARCHAR(50),
  valid_from      DATE,
  valid_to        DATE,
  policy_number   VARCHAR(24),
  policy_type     VARCHAR(30),
  od_valid_to     DATE,
  insured_name    VARCHAR(80),
  chassis_no      CHAR(17),
  issued_at       DATETIME,
  dwh_batch_id    INT          NOT NULL,
  dwh_loaded_at   DATETIME     NOT NULL,
  PRIMARY KEY (policy_id, dwh_batch_id),
  KEY idx_dwh_batch_id (dwh_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- from theft_records.theft_shredding (changes tracked by updated_at)
CREATE TABLE IF NOT EXISTS bronze.theft_shredding (
  case_id          INT          NOT NULL,
  plate_number     VARCHAR(20),
  report_type      VARCHAR(20),
  report_date      DATE,
  case_status      VARCHAR(12),
  recovery_date    DATE,
  reference_no     VARCHAR(32),
  reporting_office VARCHAR(80),
  state_name       VARCHAR(60),
  chassis_no       CHAR(17),
  make_model       VARCHAR(50),
  colour           VARCHAR(20),
  updated_at       DATE,
  dwh_batch_id     INT          NOT NULL,
  dwh_loaded_at    DATETIME     NOT NULL,
  PRIMARY KEY (case_id, dwh_batch_id),
  KEY idx_dwh_batch_id (dwh_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- from roadcapture.capture_log (new rows tracked by ingested_at, not capture_time:
-- about 1% of reads arrive more than a day after they were taken)
CREATE TABLE IF NOT EXISTS bronze.capture_log (
  capture_id      INT          NOT NULL,
  plate_no        VARCHAR(20),
  capture_time    DATETIME,
  location        VARCHAR(100),
  vehicle_color   VARCHAR(20),
  vehicle_type    VARCHAR(20),
  camera_id       VARCHAR(20),
  camera_type     VARCHAR(12),
  capture_state   VARCHAR(60),
  latitude        DECIMAL(9,6),
  longitude       DECIMAL(9,6),
  ocr_confidence  DECIMAL(4,3),
  ingested_at     DATETIME,
  dwh_batch_id    INT          NOT NULL,
  dwh_loaded_at   DATETIME     NOT NULL,
  PRIMARY KEY (capture_id, dwh_batch_id),
  KEY idx_dwh_batch_id (dwh_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
