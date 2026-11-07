-- =====================================================================================
-- ddl_silver.sql -- silver: one clean row per real-world record
-- Run once, after 00_setup_mysql.sql:
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/silver/ddl_silver.sql
-- Safe to run again. run_pipeline.py rebuilds every silver table from bronze on each run,
-- so these tables never need migrating by hand: change the DDL, drop the table, rerun.
-- The cleaning rules are in docs/DATA_MODEL.md, section 6.
-- =====================================================================================

-- ---------- reference data, loaded as they are from ref/*.csv ----------

CREATE TABLE IF NOT EXISTS silver.ref_states (
  state_key                CHAR(2)       NOT NULL,
  state_name               VARCHAR(60)   NOT NULL,
  vehicles_2015_thousands  INT,
  vehicle_share            DECIMAL(8,6),
  theft_rate_multiplier    DECIMAL(5,2),
  name_region              VARCHAR(20),
  camera_city_share        DECIMAL(4,2),
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS silver.ref_rto_offices (
  state_key         CHAR(2)       NOT NULL,
  plate_state_code  CHAR(2)       NOT NULL,
  rto_number        SMALLINT      NOT NULL,
  rto_code          VARCHAR(6)    NOT NULL,
  rto_name          VARCHAR(120),
  valid_from        DATE,
  valid_to          DATE,
  commercial_only   TINYINT,
  note              VARCHAR(100),
  PRIMARY KEY (rto_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS silver.ref_toll_plazas (
  plaza_id         VARCHAR(20)   NOT NULL,
  plaza_name       VARCHAR(100),
  state_key        CHAR(2),
  state_name       VARCHAR(60),
  latitude         DECIMAL(9,6),
  longitude        DECIMAL(9,6),
  project_type     VARCHAR(30),
  traffic_per_day  INT,
  PRIMARY KEY (plaza_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS silver.ref_city_cameras (
  camera_id    VARCHAR(20)   NOT NULL,
  city         VARCHAR(40),
  state_key    CHAR(2),
  latitude     DECIMAL(9,6),
  longitude    DECIMAL(9,6),
  city_weight  DECIMAL(6,2),
  PRIMARY KEY (camera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS silver.ref_insurers (
  insurer_name     VARCHAR(50)   NOT NULL,     -- as written on policies
  current_company  VARCHAR(50)   NOT NULL,     -- differs only for Bharti AXA and Reliance General
  sector           VARCHAR(7)    NOT NULL,     -- Public | Private
  note             VARCHAR(100),
  PRIMARY KEY (insurer_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS silver.ref_vehicle_classes (
  vehicle_class  VARCHAR(40)   NOT NULL,       -- as written in the registry
  vehicle_group  VARCHAR(8)    NOT NULL,       -- 2W, CAR, TAXI, LCV, TRUCK, BUS, 3W_P, 3W_G, ERICK, TRACTOR
  description    VARCHAR(60),
  PRIMARY KEY (vehicle_class)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- every distinct plate string seen in any source, and what it parses to ----------

CREATE TABLE IF NOT EXISTS silver.plate_lookup (
  raw_plate     VARCHAR(20)   NOT NULL,        -- as a source wrote it
  plate         VARCHAR(20)   NULL,            -- canonical plate; NULL if it does not parse
  plate_format  VARCHAR(14)   NOT NULL,        -- STANDARD | DELHI | BH | EMPTY | INVALID_FORMAT
  PRIMARY KEY (raw_plate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- registrations: every version of every vehicle, one row per change ----------

CREATE TABLE IF NOT EXISTS silver.registrations (
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
  chassis_no         CHAR(17)     NOT NULL,    -- the vehicle's identity
  rto_code           VARCHAR(6),
  rto_name           VARCHAR(120),
  state_name         VARCHAR(60),
  transport_category VARCHAR(15),
  owner_type         VARCHAR(12),
  owner_serial       TINYINT,
  reg_valid_upto     DATE,
  reg_status         VARCHAR(12),
  last_updated       DATE         NOT NULL,    -- the day this version started
  plate              VARCHAR(20),              -- canonical plate
  vehicle_group      VARCHAR(8),               -- from ref_vehicle_classes
  is_current         TINYINT      NOT NULL,    -- 1 for the vehicle's latest version
  dwh_batch_id       INT          NOT NULL,    -- bronze batch that brought this version
  PRIMARY KEY (chassis_no, last_updated),
  KEY idx_plate_current (plate, is_current),
  KEY idx_dwh_batch_id (dwh_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- policies: one row per policy ----------

CREATE TABLE IF NOT EXISTS silver.policies (
  policy_id        INT          NOT NULL,
  vehicle_number   VARCHAR(20),
  insurer          VARCHAR(50),
  valid_from       DATE,
  valid_to         DATE,
  policy_number    VARCHAR(24),
  policy_type      VARCHAR(30),
  od_valid_to      DATE,
  insured_name     VARCHAR(80),
  chassis_no       CHAR(17),                   -- how a policy is tied to its vehicle
  issued_at        DATETIME,
  plate            VARCHAR(20),                -- canonical plate; NULL if filed under NEW or unparseable
  has_tp_cover     TINYINT      NOT NULL,      -- 0 only for Standalone OD
  filed_under_new  TINYINT      NOT NULL,
  dwh_batch_id     INT          NOT NULL,
  PRIMARY KEY (policy_id),
  KEY idx_chassis_no (chassis_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- theft and scrapping cases: latest state of each case ----------

CREATE TABLE IF NOT EXISTS silver.theft_shredding (
  case_id             INT          NOT NULL,
  plate_number        VARCHAR(20),
  report_type         VARCHAR(20),
  report_date         DATE,
  case_status         VARCHAR(12),
  recovery_date       DATE,
  reference_no        VARCHAR(32),
  reporting_office    VARCHAR(80),
  state_name          VARCHAR(60),
  chassis_no          CHAR(17),                -- from the case, else from the registry by plate
  make_model          VARCHAR(50),
  colour              VARCHAR(20),
  updated_at          DATE,
  plate               VARCHAR(20),             -- canonical plate
  case_type           VARCHAR(8)   NOT NULL,   -- STOLEN | SCRAPPED (the source says SHREDDED)
  chassis_from_plate  TINYINT      NOT NULL,   -- 1 if chassis_no came from the registry
  dwh_batch_id        INT          NOT NULL,
  PRIMARY KEY (case_id),
  KEY idx_chassis_no (chassis_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- camera reads: one row per read, matched to a vehicle where possible ----------

CREATE TABLE IF NOT EXISTS silver.capture_log (
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
  plate           VARCHAR(20),                 -- canonical plate, where the read parses
  read_status     VARCHAR(16)  NOT NULL,       -- MATCHED | NOT_IN_REGISTRY | INVALID_FORMAT | UNREADABLE
  chassis_no      CHAR(17),                    -- the matched vehicle
  is_duplicate    TINYINT      NOT NULL,       -- 1 for a second read by the same camera within 5 s
  dwh_batch_id    INT          NOT NULL,
  PRIMARY KEY (capture_id),
  KEY idx_chassis_time (chassis_no, capture_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
