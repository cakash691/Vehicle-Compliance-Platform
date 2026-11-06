-- 02_load_base.sql -- bulk-load the base snapshot (everything ingested up to 2026-11-03 23:59:59)
-- Run from the realistic_data_v2 folder (file paths are relative to where you start mysql):
--   mysql --local-infile=1 -h 127.0.0.1 -u iia_app -piia_app_pw < mysql/02_load_base.sql
-- Needs local_infile enabled on the server once:  mysql -u root -p -e "SET GLOBAL local_infile = 1;"

SELECT 'loading registrations ...' AS step;
LOAD DATA LOCAL INFILE 'sources/registrations.csv'
  INTO TABLE rto_registration.registrations
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (reg_id, reg_no, owner_name, make_model, registration_date, maker, vehicle_class, body_type, fuel_type, colour, chassis_no, rto_code, rto_name, state_name, transport_category, owner_type, owner_serial, @reg_valid_upto, reg_status, last_updated)
  SET reg_valid_upto = NULLIF(@reg_valid_upto, '');

SELECT 'loading policies ...' AS step;
LOAD DATA LOCAL INFILE 'sources/policies.csv'
  INTO TABLE insurance.policies
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (policy_id, vehicle_number, insurer, valid_from, valid_to, policy_number, policy_type, @od_valid_to, insured_name, chassis_no, issued_at)
  SET od_valid_to = NULLIF(@od_valid_to, '');

SELECT 'loading capture_log ... (about 450k rows, ~10-30 s)' AS step;
LOAD DATA LOCAL INFILE 'sources/capture_log.csv'
  INTO TABLE roadcapture.capture_log
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (capture_id, plate_no, capture_time, location, vehicle_color, vehicle_type, camera_id, camera_type, capture_state, latitude, longitude, ocr_confidence, ingested_at);

SELECT 'loading theft_shredding ...' AS step;
LOAD DATA LOCAL INFILE 'sources/theft_shredding.csv'
  INTO TABLE theft_records.theft_shredding
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  IGNORE 1 LINES
  (case_id, plate_number, report_type, report_date, case_status, @recovery_date, reference_no, reporting_office, state_name, @chassis_no, make_model, colour, updated_at)
  SET recovery_date = NULLIF(@recovery_date, ''),
      chassis_no = NULLIF(@chassis_no, '');

SELECT 'registrations' AS source_table, COUNT(*) AS rows_loaded FROM rto_registration.registrations
UNION ALL SELECT 'policies', COUNT(*) FROM insurance.policies
UNION ALL SELECT 'capture_log', COUNT(*) FROM roadcapture.capture_log
UNION ALL SELECT 'theft_shredding', COUNT(*) FROM theft_records.theft_shredding;
