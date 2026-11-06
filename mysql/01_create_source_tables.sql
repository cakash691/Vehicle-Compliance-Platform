-- =====================================================================================
-- 01_create_source_tables.sql  --  v2 schema for the four independent source databases
-- Run once (as iia_app or root) BEFORE loading:
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/01_create_source_tables.sql
-- The first columns of every table are exactly the v1 columns, so run_etl.py and app.py
-- keep working; everything after them is new in v2.
-- WARNING: drops and recreates the four source tables, and resets the warehouse
-- (vehicle_360 + etl_watermark) so that no stale watermark survives -- see README.
-- =====================================================================================

-- ---------- on-road ANPR captures (the driving table) ----------
DROP TABLE IF EXISTS roadcapture.capture_log;
CREATE TABLE roadcapture.capture_log (
  capture_id      INT          NOT NULL AUTO_INCREMENT,
  plate_no        VARCHAR(20)  NOT NULL,          -- '' when the camera could not read the plate
  capture_time    DATETIME     NOT NULL,          -- when the vehicle passed the camera
  location        VARCHAR(100) NOT NULL,
  vehicle_color   VARCHAR(20),
  vehicle_type    VARCHAR(20),                    -- camera's classification, not the RTO body type
  camera_id       VARCHAR(20)  NOT NULL,          -- NHAI-#### (toll plaza) or ITMS-XXX-### (city junction)
  camera_type     VARCHAR(12)  NOT NULL,          -- TOLL_ANPR | CITY_ANPR
  capture_state   VARCHAR(60),
  latitude        DECIMAL(9,6),
  longitude       DECIMAL(9,6),
  ocr_confidence  DECIMAL(4,3),
  ingested_at     DATETIME     NOT NULL,          -- when the read landed in this database
  PRIMARY KEY (capture_id),
  KEY idx_capture_time (capture_time),
  KEY idx_ingested_at (ingested_at),
  KEY idx_plate_no (plate_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- insurer feed (full policy history in force on/after 2023-01-01) ----------
DROP TABLE IF EXISTS insurance.policies;
CREATE TABLE insurance.policies (
  policy_id       INT          NOT NULL AUTO_INCREMENT,
  vehicle_number  VARCHAR(20)  NOT NULL,          -- format differs by insurer; 'NEW' = not yet registered
  insurer         VARCHAR(50)  NOT NULL,
  valid_from      DATE         NOT NULL,
  valid_to        DATE         NOT NULL,
  policy_number   VARCHAR(24)  NOT NULL,
  policy_type     VARCHAR(30)  NOT NULL,          -- 'Standalone OD' does NOT include third-party cover
  od_valid_to     DATE         NULL,
  insured_name    VARCHAR(80),
  chassis_no      CHAR(17),
  issued_at       DATETIME     NOT NULL,
  PRIMARY KEY (policy_id),
  UNIQUE KEY uk_policy_number (policy_number),
  KEY idx_vehicle_number (vehicle_number),
  KEY idx_chassis_no (chassis_no),
  KEY idx_issued_at (issued_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- RTO registry ----------
DROP TABLE IF EXISTS rto_registration.registrations;
CREATE TABLE rto_registration.registrations (
  reg_id             INT          NOT NULL AUTO_INCREMENT,
  reg_no             VARCHAR(20)  NOT NULL,
  owner_name         VARCHAR(80),
  make_model         VARCHAR(50),
  registration_date  DATE         NOT NULL,
  maker              VARCHAR(30),
  vehicle_class      VARCHAR(40),
  body_type          VARCHAR(20),
  fuel_type          VARCHAR(20),
  colour             VARCHAR(20),
  chassis_no         CHAR(17)     NOT NULL,
  rto_code           VARCHAR(6),
  rto_name           VARCHAR(120),
  state_name         VARCHAR(60),
  transport_category VARCHAR(15),
  owner_type         VARCHAR(12),
  owner_serial       TINYINT,
  reg_valid_upto     DATE         NULL,           -- NULL for transport vehicles (fitness-based)
  reg_status         VARCHAR(12)  NOT NULL,       -- ACTIVE | SCRAPPED (some scrapped vehicles are never updated!)
  last_updated       DATE         NOT NULL,       -- change-tracking column for incremental extraction
  PRIMARY KEY (reg_id),
  UNIQUE KEY uk_reg_no (reg_no),
  UNIQUE KEY uk_chassis_no (chassis_no),
  KEY idx_last_updated (last_updated)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- police theft FIRs + RVSF scrapping certificates ----------
DROP TABLE IF EXISTS theft_records.theft_shredding;
CREATE TABLE theft_records.theft_shredding (
  case_id          INT          NOT NULL AUTO_INCREMENT,
  plate_number     VARCHAR(20)  NOT NULL,
  report_type      VARCHAR(20)  NOT NULL,         -- STOLEN | SHREDDED
  report_date      DATE         NOT NULL,
  case_status      VARCHAR(12)  NOT NULL,         -- OPEN | RECOVERED (STOLEN) ; CLOSED (SHREDDED)
  recovery_date    DATE         NULL,
  reference_no     VARCHAR(32),                   -- FIR no. or Certificate-of-Deposit no.
  reporting_office VARCHAR(80),
  state_name       VARCHAR(60),
  chassis_no       CHAR(17)     NULL,
  make_model       VARCHAR(50),
  colour           VARCHAR(20),
  updated_at       DATE         NOT NULL,
  PRIMARY KEY (case_id),
  KEY idx_plate_number (plate_number),
  KEY idx_chassis_no (chassis_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- reset the warehouse so the v2 data is loaded from scratch ----------
DROP TABLE IF EXISTS vehicle_dwh.vehicle_360;
DROP TABLE IF EXISTS vehicle_dwh.etl_watermark;
