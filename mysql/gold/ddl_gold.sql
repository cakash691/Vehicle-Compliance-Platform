-- =====================================================================================
-- ddl_gold.sql -- gold: the star schema (5 dimensions, 4 facts) and the vehicle_360 view
-- Run once, after ddl_silver.sql:
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/gold/ddl_gold.sql
-- Safe to run again: it never drops or empties a table, and it replaces the view.
--
-- What each column means: docs/DATA_MODEL.md, section 13. Facts point at dimensions
-- through integer keys; when nothing matches they point at the dimension's -1 row
-- ("Unknown" or "Not yet"), never at NULL. Keys are not enforced as foreign keys;
-- the quality tests check them instead.
-- =====================================================================================

-- ---------- dimensions ----------

CREATE TABLE IF NOT EXISTS gold.dim_date (
  date_key     INT          NOT NULL,          -- YYYYMMDD; -1 = not yet or unknown
  full_date    DATE         NULL,
  year         SMALLINT     NULL,
  quarter      TINYINT      NULL,
  month        TINYINT      NULL,
  month_name   VARCHAR(9)   NULL,
  month_label  CHAR(7)      NULL,              -- 2026-11, for chart axes
  fiscal_year  CHAR(9)      NULL,              -- Indian financial year, April to March: FY2026-27
  day_of_week  TINYINT      NULL,              -- 1 = Monday ... 7 = Sunday
  is_weekend   TINYINT      NULL,
  PRIMARY KEY (date_key),
  KEY idx_full_date (full_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gold.dim_state (
  state_key   INT          NOT NULL AUTO_INCREMENT,
  state_code  CHAR(2)      NOT NULL,           -- from ref/states.csv
  state_name  VARCHAR(60)  NOT NULL,
  PRIMARY KEY (state_key),
  UNIQUE KEY uk_state_code (state_code),
  KEY idx_state_name (state_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gold.dim_location (
  location_key     INT           NOT NULL AUTO_INCREMENT,
  camera_id        VARCHAR(20)   NOT NULL,     -- NHAI-0139 (toll plaza) or ITMS-DEL-001 (city junction)
  camera_type      VARCHAR(12)   NOT NULL,     -- TOLL_ANPR | CITY_ANPR
  place_name       VARCHAR(100)  NOT NULL,     -- as the camera reports it
  city             VARCHAR(40)   NULL,         -- city cameras only
  state_name       VARCHAR(60)   NOT NULL,
  latitude         DECIMAL(9,6)  NULL,
  longitude        DECIMAL(9,6)  NULL,
  traffic_per_day  INT           NULL,         -- NHAI's published figure, toll plazas only
  PRIMARY KEY (location_key),
  UNIQUE KEY uk_camera_id (camera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gold.dim_insurer (
  insurer_key      INT          NOT NULL AUTO_INCREMENT,
  insurer_name     VARCHAR(50)  NOT NULL,      -- as written on the policy
  current_company  VARCHAR(50)  NOT NULL,      -- differs only for Bharti AXA and Reliance General
  sector           VARCHAR(7)   NOT NULL,      -- Public | Private
  PRIMARY KEY (insurer_key),
  UNIQUE KEY uk_insurer_name (insurer_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One row per version of a vehicle (SCD type 2). A new version starts whenever the
-- registry records a change; valid_from/valid_to bound each version.
CREATE TABLE IF NOT EXISTS gold.dim_vehicle (
  vehicle_key         INT           NOT NULL AUTO_INCREMENT,
  chassis_no          CHAR(17)      NOT NULL,  -- natural key
  plate               VARCHAR(20)   NULL,
  vehicle_group       VARCHAR(8)    NULL,
  vehicle_class       VARCHAR(40)   NULL,
  body_type           VARCHAR(20)   NULL,
  maker               VARCHAR(30)   NULL,
  make_model          VARCHAR(50)   NULL,
  fuel_type           VARCHAR(20)   NULL,
  colour              VARCHAR(20)   NULL,
  transport_category  VARCHAR(15)   NULL,
  registration_date   DATE          NULL,
  rto_code            VARCHAR(6)    NULL,
  rto_name            VARCHAR(120)  NULL,
  state_name          VARCHAR(60)   NULL,      -- registration state
  owner_type          VARCHAR(12)   NULL,
  owner_name          VARCHAR(80)   NULL,      -- personal data, used only by vehicle_360
  owner_serial        TINYINT       NULL,
  reg_status          VARCHAR(12)   NULL,
  reg_valid_upto      DATE          NULL,
  last_updated        DATE          NOT NULL,  -- the registry change that created this version
  valid_from          DATE          NOT NULL,  -- 1900-01-01 for a vehicle's first version
  valid_to            DATE          NOT NULL,  -- 9999-12-31 for the current version
  is_current          TINYINT       NOT NULL,
  dwh_batch_id        INT           NOT NULL,
  PRIMARY KEY (vehicle_key),
  UNIQUE KEY uk_version (chassis_no, last_updated),
  KEY idx_chassis_valid (chassis_no, valid_from),
  KEY idx_plate (plate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- facts ----------

-- one row per camera read, without duplicate lane reads
CREATE TABLE IF NOT EXISTS gold.fact_sighting (
  capture_id           INT           NOT NULL,
  date_key             INT           NOT NULL,
  capture_time         DATETIME      NOT NULL,
  vehicle_key          INT           NOT NULL,  -- version valid on the capture date; -1 if no vehicle matched
  location_key         INT           NOT NULL,
  state_key            INT           NOT NULL,  -- state the camera is in
  plate_read           VARCHAR(20)   NOT NULL,
  read_status          VARCHAR(16)   NOT NULL,  -- MATCHED | NOT_IN_REGISTRY | INVALID_FORMAT | UNREADABLE
  status_at_sighting   VARCHAR(10)   NOT NULL,  -- INSURED | EXPIRED | NO_POLICY | STOLEN | SCRAPPED | UNKNOWN
  is_uninsured         TINYINT       NOT NULL,
  camera_vehicle_type  VARCHAR(20)   NULL,
  ocr_confidence       DECIMAL(4,3)  NULL,
  ingested_at          DATETIME      NULL,
  dwh_batch_id         INT           NOT NULL,
  PRIMARY KEY (capture_id),
  KEY idx_vehicle_date (vehicle_key, date_key),
  KEY idx_date_key (date_key),
  KEY idx_location_key (location_key),
  KEY idx_state_key (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- one row per policy
CREATE TABLE IF NOT EXISTS gold.fact_policy (
  policy_id            INT          NOT NULL,
  policy_number        VARCHAR(24)  NOT NULL,
  vehicle_key          INT          NOT NULL,   -- version valid on the issue date
  insurer_key          INT          NOT NULL,
  state_key            INT          NOT NULL,   -- vehicle's registration state
  issued_date_key      INT          NOT NULL,
  valid_from_date_key  INT          NOT NULL,
  valid_to_date_key    INT          NOT NULL,
  policy_type          VARCHAR(30)  NOT NULL,
  has_tp_cover         TINYINT      NOT NULL,
  cover_days           SMALLINT     NOT NULL,
  renewal_gap_days     SMALLINT     NULL,       -- days without TP cover before this policy; NULL for a first policy
  filed_under_new      TINYINT      NOT NULL,
  dwh_batch_id         INT          NOT NULL,
  PRIMARY KEY (policy_id),
  KEY idx_vehicle_key (vehicle_key),
  KEY idx_insurer_key (insurer_key),
  KEY idx_state_key (state_key),
  KEY idx_valid_from (valid_from_date_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- one row per theft or scrapping case, rewritten each night as cases move
CREATE TABLE IF NOT EXISTS gold.fact_theft_case (
  case_id                 INT          NOT NULL,
  reference_no            VARCHAR(32)  NULL,
  case_type               VARCHAR(8)   NOT NULL,  -- STOLEN | SCRAPPED
  case_status             VARCHAR(10)  NOT NULL,  -- OPEN | RECOVERED | CLOSED
  vehicle_key             INT          NOT NULL,  -- version valid on the report date
  state_key               INT          NOT NULL,
  report_date_key         INT          NOT NULL,
  recovery_date_key       INT          NOT NULL,  -- -1 until recovered
  days_to_recovery        SMALLINT     NULL,
  sightings_after_report  SMALLINT     NOT NULL,
  dwh_batch_id            INT          NOT NULL,
  PRIMARY KEY (case_id),
  KEY idx_vehicle_key (vehicle_key),
  KEY idx_state_key (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- one row per vehicle per month, from January 2023
CREATE TABLE IF NOT EXISTS gold.fact_compliance_monthly (
  month_key               INT          NOT NULL,  -- date key of the month's first day
  vehicle_key             INT          NOT NULL,  -- version valid on status_as_of
  state_key               INT          NOT NULL,  -- registration state
  status_as_of            DATE         NOT NULL,  -- month's last day; the run's as_of for the current month
  status                  VARCHAR(10)  NOT NULL,
  is_uninsured            TINYINT      NOT NULL,
  days_since_cover_ended  SMALLINT     NULL,
  vehicle_age_years       TINYINT      NOT NULL,
  sightings_in_month      SMALLINT     NOT NULL,
  dwh_batch_id            INT          NOT NULL,
  PRIMARY KEY (month_key, vehicle_key),
  KEY idx_state_month (state_key, month_key),
  KEY idx_vehicle_key (vehicle_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- views ----------

-- One row per vehicle seen on camera: its latest sighting, latest TP policy and status on the
-- warehouse's latest as_of date. Same columns and status wording as the prototype's table, so
-- app.py and evaluate_etl.py work with it (python3 evaluate_etl.py --database gold).
CREATE OR REPLACE VIEW gold.vehicle_360 AS
SELECT v.plate             AS plate_canonical,
       v.owner_name,
       v.make_model,
       v.registration_date,
       p.insurer_name      AS insurer,
       p.policy_valid_to,
       CASE m.status WHEN 'STOLEN' THEN 'STOLEN' WHEN 'SCRAPPED' THEN 'SHREDDED' ELSE '-' END AS theft_flag,
       s.place_name        AS last_seen_location,
       s.capture_time      AS last_seen_time,
       CASE m.status
            WHEN 'INSURED'   THEN 'OK - INSURED & CLEAR'
            WHEN 'EXPIRED'   THEN 'INSURANCE EXPIRED -> FLAG'
            WHEN 'NO_POLICY' THEN 'NO INSURANCE ON FILE -> FLAG'
            WHEN 'STOLEN'    THEN 'STOLEN/SHREDDED -> FLAG (STOLEN)'
            WHEN 'SCRAPPED'  THEN 'STOLEN/SHREDDED -> FLAG (SCRAPPED)'
       END                 AS status
FROM (
    SELECT dv.chassis_no, f.capture_time, l.place_name,
           ROW_NUMBER() OVER (PARTITION BY dv.chassis_no ORDER BY f.capture_time DESC, f.capture_id DESC) AS rn
    FROM gold.fact_sighting f
    JOIN gold.dim_vehicle dv ON dv.vehicle_key = f.vehicle_key
    JOIN gold.dim_location l ON l.location_key = f.location_key
    WHERE f.vehicle_key <> -1
) s
JOIN gold.dim_vehicle v ON v.chassis_no = s.chassis_no AND v.is_current = 1
JOIN gold.fact_compliance_monthly m
  ON m.vehicle_key = v.vehicle_key
 AND m.month_key = (SELECT MAX(month_key) FROM gold.fact_compliance_monthly)
LEFT JOIN (
    SELECT dv.chassis_no, i.insurer_name, d.full_date AS policy_valid_to,
           ROW_NUMBER() OVER (PARTITION BY dv.chassis_no ORDER BY fp.valid_to_date_key DESC, fp.policy_id DESC) AS rn
    FROM gold.fact_policy fp
    JOIN gold.dim_vehicle dv ON dv.vehicle_key = fp.vehicle_key
    JOIN gold.dim_insurer i ON i.insurer_key = fp.insurer_key
    JOIN gold.dim_date d ON d.date_key = fp.valid_to_date_key
    WHERE fp.has_tp_cover = 1
) p ON p.chassis_no = v.chassis_no AND p.rn = 1
WHERE s.rn = 1;
