-- 03_load_daily_2026-11-06.sql -- one nightly batch. New rows are appended (IGNORE = safe to re-run);
-- registrations and theft cases may be UPDATES of existing rows, so they use REPLACE (upsert by primary key).
-- Run from the project folder (file paths are relative to where you start mysql):
--   mysql --local-infile=1 -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/03_load_daily_2026-11-06.sql
-- Needs local_infile enabled on the server once:  mysql -u root -p -e "SET GLOBAL local_infile = 1;"

LOAD DATA LOCAL INFILE 'daily/2026-11-06/registrations.csv'
  REPLACE INTO TABLE rto_registration.registrations
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (reg_id, reg_no, owner_name, make_model, registration_date, maker, vehicle_class, body_type, fuel_type, colour, chassis_no, rto_code, rto_name, state_name, transport_category, owner_type, owner_serial, @reg_valid_upto, reg_status, last_updated)
  SET reg_valid_upto = NULLIF(@reg_valid_upto, '');

LOAD DATA LOCAL INFILE 'daily/2026-11-06/policies.csv'
  IGNORE INTO TABLE insurance.policies
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (policy_id, vehicle_number, insurer, valid_from, valid_to, policy_number, policy_type, @od_valid_to, insured_name, chassis_no, issued_at)
  SET od_valid_to = NULLIF(@od_valid_to, '');

LOAD DATA LOCAL INFILE 'daily/2026-11-06/capture_log.csv'
  IGNORE INTO TABLE roadcapture.capture_log
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (capture_id, plate_no, capture_time, location, vehicle_color, vehicle_type, camera_id, camera_type, capture_state, latitude, longitude, ocr_confidence, ingested_at);

LOAD DATA LOCAL INFILE 'daily/2026-11-06/theft_shredding.csv'
  REPLACE INTO TABLE theft_records.theft_shredding
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (case_id, plate_number, report_type, report_date, case_status, @recovery_date, reference_no, reporting_office, state_name, @chassis_no, make_model, colour, updated_at)
  SET recovery_date = NULLIF(@recovery_date, ''),
      chassis_no = NULLIF(@chassis_no, '');

SELECT '2026-11-06' AS batch,
       (SELECT COUNT(*) FROM roadcapture.capture_log WHERE DATE(ingested_at) = '2026-11-06') AS captures_ingested_that_day,
       (SELECT COUNT(*) FROM roadcapture.capture_log WHERE DATE(ingested_at) = '2026-11-06' AND DATE(capture_time) < '2026-11-06') AS of_which_late_arrivals;
