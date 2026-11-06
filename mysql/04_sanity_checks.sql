-- =====================================================================================
-- 04_sanity_checks.sql -- quick checks that the load worked and a first look at the data.
--   mysql -h 127.0.0.1 -u iia_app -piia_app_pw -t < mysql/04_sanity_checks.sql
-- (These only inspect the sources. The integration / decision queries are the next step.)
-- =====================================================================================

-- 1. Row counts and time coverage
SELECT 'registrations' AS source_table, COUNT(*) AS n_rows, MIN(registration_date) AS earliest, MAX(registration_date) AS latest FROM rto_registration.registrations
UNION ALL SELECT 'policies', COUNT(*), MIN(valid_from), MAX(valid_to) FROM insurance.policies
UNION ALL SELECT 'capture_log', COUNT(*), DATE(MIN(capture_time)), DATE(MAX(capture_time)) FROM roadcapture.capture_log
UNION ALL SELECT 'theft_shredding', COUNT(*), MIN(report_date), MAX(report_date) FROM theft_records.theft_shredding;

-- 2. Fleet mix in the registry
SELECT vehicle_class, COUNT(*) AS vehicles, ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM rto_registration.registrations GROUP BY vehicle_class ORDER BY vehicles DESC;

-- 3. One vehicle, four spellings of its plate (joined here on chassis_no, which only some sources carry)
SELECT r.reg_no AS rto_reg_no,
       GROUP_CONCAT(DISTINCT p.vehicle_number SEPARATOR '  |  ') AS insurer_vehicle_numbers,
       t.plate_number AS police_plate_number,
       (SELECT c.plate_no FROM roadcapture.capture_log c WHERE c.plate_no = r.reg_no LIMIT 1) AS camera_plate_no
FROM theft_records.theft_shredding t
JOIN rto_registration.registrations r ON r.chassis_no = t.chassis_no
JOIN insurance.policies p ON p.chassis_no = r.chassis_no
WHERE EXISTS (SELECT 1 FROM roadcapture.capture_log c WHERE c.plate_no = r.reg_no)
GROUP BY r.reg_no, t.plate_number
ORDER BY COUNT(DISTINCT p.vehicle_number) DESC, r.reg_no
LIMIT 5;

SELECT CASE WHEN vehicle_number = 'NEW'                   THEN 'NEW (no plate yet -- match on chassis_no)'
            WHEN vehicle_number LIKE '%-%'                THEN 'hyphenated'
            WHEN vehicle_number LIKE '% %'                THEN 'spaced'
            ELSE 'compact' END AS policy_plate_format,
       COUNT(*) AS policies
FROM insurance.policies GROUP BY policy_plate_format ORDER BY policies DESC;

-- 4. Policy types (Standalone OD carries no third-party cover)
SELECT policy_type, COUNT(*) AS policies FROM insurance.policies GROUP BY policy_type ORDER BY policies DESC;

-- 5. One insurer, two names: Reliance General became IndusInd General Insurance on 2025-09-22
SELECT insurer, MIN(DATE(issued_at)) AS first_issued, MAX(DATE(issued_at)) AS last_issued, COUNT(*) AS policies
FROM insurance.policies WHERE insurer IN ('Reliance General', 'IndusInd General Insurance', 'Bharti AXA General Insurance')
GROUP BY insurer;

-- 6. Camera feed quality
SELECT camera_type, COUNT(*) AS n_reads,
       SUM(plate_no = '')                                         AS unreadable,
       SUM(ocr_confidence < 0.80)                                 AS low_confidence,
       SUM(TIMESTAMPDIFF(HOUR, capture_time, ingested_at) >= 24)  AS arrived_a_day_late
FROM roadcapture.capture_log GROUP BY camera_type;

-- 7. Naive exact match: how many distinct captured plates exist in the RTO registry as-is?
--    (Default MySQL collations are case-insensitive, so 'mh12ab1234' = 'MH12AB1234' here.)
SELECT COUNT(*) AS distinct_plates_seen,
       SUM(EXISTS (SELECT 1 FROM rto_registration.registrations r WHERE r.reg_no = p.plate_no)) AS found_in_rto,
       ROUND(100 * SUM(EXISTS (SELECT 1 FROM rto_registration.registrations r WHERE r.reg_no = p.plate_no)) / COUNT(*), 2) AS pct_found
FROM (SELECT DISTINCT plate_no FROM roadcapture.capture_log WHERE plate_no <> '') p;

-- 8. Theft and scrappage records
SELECT report_type, case_status, COUNT(*) AS cases FROM theft_records.theft_shredding GROUP BY report_type, case_status;

-- 9. RTO says ACTIVE but an RVSF certificate says the vehicle was scrapped (source conflict)
SELECT COUNT(*) AS scrapped_but_still_active_in_rto
FROM theft_records.theft_shredding t
JOIN rto_registration.registrations r ON r.chassis_no = t.chassis_no
WHERE t.report_type = 'SHREDDED' AND r.reg_status = 'ACTIVE';
