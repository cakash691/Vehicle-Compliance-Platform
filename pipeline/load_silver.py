"""
load_silver.py -- rebuild silver from bronze: one clean row per real-world record.

Silver is rebuilt in full on every run; at this size that takes seconds. It keeps silver
simple and always consistent with bronze, and a fix to a cleaning rule reaches every past
row on the next run. Bronze is what makes this possible: it holds every row the sources
ever sent, including the versions they have since overwritten.

Order matters. The plate lookup and the registrations come first, because theft cases and
camera reads find their vehicle through the registry's plates. The cleaning rules are
explained in docs/DATA_MODEL.md, section 6.
"""

import csv
import os

from db_config import connect
from pipeline import runlog
from pipeline.plates import canonical_plate

REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ref")
REF_FILES = [  # silver table, file in ref/
    ("silver.ref_states", "states.csv"),
    ("silver.ref_rto_offices", "rto_offices.csv"),
    ("silver.ref_toll_plazas", "toll_plazas.csv"),
    ("silver.ref_city_cameras", "city_cameras.csv"),
    ("silver.ref_insurers", "insurers.csv"),
    ("silver.ref_vehicle_classes", "vehicle_classes.csv"),
]

# Every version of every vehicle. A vehicle's versions are ordered by last_updated; the latest
# is the current one. copy_rank drops a version that bronze happens to hold twice.
REGISTRATIONS = """
INSERT INTO silver.registrations (
    reg_id, reg_no, owner_name, make_model, registration_date, maker, vehicle_class, body_type,
    fuel_type, colour, chassis_no, rto_code, rto_name, state_name, transport_category, owner_type,
    owner_serial, reg_valid_upto, reg_status, last_updated, plate, vehicle_group, is_current, dwh_batch_id)
SELECT v.reg_id, v.reg_no, v.owner_name, v.make_model, v.registration_date, v.maker, v.vehicle_class,
       v.body_type, v.fuel_type, v.colour, v.chassis_no, v.rto_code, v.rto_name, v.state_name,
       v.transport_category, v.owner_type, v.owner_serial, v.reg_valid_upto, v.reg_status, v.last_updated,
       pl.plate, vc.vehicle_group, v.version_rank = 1, v.dwh_batch_id
FROM (
    SELECT b.*,
           ROW_NUMBER() OVER (PARTITION BY b.chassis_no ORDER BY b.last_updated DESC, b.dwh_batch_id DESC) AS version_rank,
           ROW_NUMBER() OVER (PARTITION BY b.chassis_no, b.last_updated ORDER BY b.dwh_batch_id DESC) AS copy_rank
    FROM bronze.registrations b
) v
LEFT JOIN silver.plate_lookup pl ON pl.raw_plate = v.reg_no
LEFT JOIN silver.ref_vehicle_classes vc ON vc.vehicle_class = v.vehicle_class
WHERE v.copy_rank = 1
"""

# Policies never change once issued, so bronze holds each one once. Rules 2 and 3:
# the vehicle is the chassis, and every policy type except Standalone OD includes TP cover.
POLICIES = """
INSERT INTO silver.policies (
    policy_id, vehicle_number, insurer, valid_from, valid_to, policy_number, policy_type, od_valid_to,
    insured_name, chassis_no, issued_at, plate, has_tp_cover, filed_under_new, dwh_batch_id)
SELECT b.policy_id, b.vehicle_number, b.insurer, b.valid_from, b.valid_to, b.policy_number, b.policy_type,
       b.od_valid_to, b.insured_name, b.chassis_no, b.issued_at,
       IF(b.vehicle_number = 'NEW', NULL, pl.plate),
       b.policy_type <> 'Standalone OD',
       b.vehicle_number = 'NEW',
       b.dwh_batch_id
FROM bronze.policies b
LEFT JOIN silver.plate_lookup pl ON pl.raw_plate = b.vehicle_number
"""

# The latest state of each case. A case without a chassis gets the chassis of the
# registered vehicle with the same plate.
THEFT = """
INSERT INTO silver.theft_shredding (
    case_id, plate_number, report_type, report_date, case_status, recovery_date, reference_no,
    reporting_office, state_name, chassis_no, make_model, colour, updated_at, plate, case_type,
    chassis_from_plate, dwh_batch_id)
SELECT t.case_id, t.plate_number, t.report_type, t.report_date, t.case_status, t.recovery_date,
       t.reference_no, t.reporting_office, t.state_name, COALESCE(t.chassis_no, r.chassis_no),
       t.make_model, t.colour, t.updated_at, pl.plate,
       IF(t.report_type = 'SHREDDED', 'SCRAPPED', t.report_type),
       t.chassis_no IS NULL AND r.chassis_no IS NOT NULL,
       t.dwh_batch_id
FROM (
    SELECT b.*,
           ROW_NUMBER() OVER (PARTITION BY b.case_id ORDER BY b.updated_at DESC, b.dwh_batch_id DESC) AS version_rank
    FROM bronze.theft_shredding b
) t
LEFT JOIN silver.plate_lookup pl ON pl.raw_plate = t.plate_number
LEFT JOIN silver.registrations r ON r.plate = pl.plate AND r.is_current = 1
WHERE t.version_rank = 1
"""

# Every camera read. A read is a duplicate when the same camera read the same plate
# within the previous 5 seconds (an adjacent lane); silver flags it and gold leaves it out.
CAPTURES = """
INSERT INTO silver.capture_log (
    capture_id, plate_no, capture_time, location, vehicle_color, vehicle_type, camera_id, camera_type,
    capture_state, latitude, longitude, ocr_confidence, ingested_at, plate, read_status, chassis_no,
    is_duplicate, dwh_batch_id)
SELECT c.capture_id, c.plate_no, c.capture_time, c.location, c.vehicle_color, c.vehicle_type, c.camera_id,
       c.camera_type, c.capture_state, c.latitude, c.longitude, c.ocr_confidence, c.ingested_at,
       pl.plate,
       CASE WHEN c.plate_no IS NULL OR pl.plate_format = 'EMPTY' THEN 'UNREADABLE'
            WHEN pl.plate IS NULL THEN 'INVALID_FORMAT'
            WHEN r.chassis_no IS NULL THEN 'NOT_IN_REGISTRY'
            ELSE 'MATCHED' END,
       r.chassis_no,
       COALESCE(c.plate_no <> '' AND TIMESTAMPDIFF(SECOND, c.previous_read, c.capture_time) <= 5, 0),
       c.dwh_batch_id
FROM (
    SELECT b.*,
           LAG(b.capture_time) OVER (PARTITION BY b.camera_id, b.plate_no ORDER BY b.capture_time, b.capture_id) AS previous_read
    FROM bronze.capture_log b
) c
LEFT JOIN silver.plate_lookup pl ON pl.raw_plate = c.plate_no
LEFT JOIN silver.registrations r ON r.plate = pl.plate AND r.is_current = 1
"""


def insert_rows(cur, table, columns, rows, chunk=5000):
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
    for i in range(0, len(rows), chunk):
        cur.executemany(sql, rows[i:i + chunk])


def load_refs(cur):
    """Reload the ref_* tables from the CSV files in ref/ (they are small and already clean)."""
    total = 0
    for table, filename in REF_FILES:
        with open(os.path.join(REF_DIR, filename), newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            columns = next(reader)
            rows = [[value if value != "" else None for value in row] for row in reader]
        cur.execute(f"TRUNCATE TABLE {table}")
        insert_rows(cur, table, columns, rows)
        total += len(rows)
    return total


def build_plate_lookup(cur):
    """Parse every distinct plate string in bronze once (rule 1), so the SQL below can join on it."""
    cur.execute("SELECT reg_no FROM bronze.registrations "
                "UNION SELECT vehicle_number FROM bronze.policies "
                "UNION SELECT plate_number FROM bronze.theft_shredding "
                "UNION SELECT plate_no FROM bronze.capture_log")
    rows = [(raw, *canonical_plate(raw)) for (raw,) in cur.fetchall() if raw is not None]
    cur.execute("TRUNCATE TABLE silver.plate_lookup")
    insert_rows(cur, "silver.plate_lookup", ["raw_plate", "plate", "plate_format"], rows)
    return len(rows)


def rebuild(table, sql):
    def build(cur):
        cur.execute(f"TRUNCATE TABLE {table}")
        cur.execute(sql)
        return cur.rowcount
    return build


STEPS = [
    ("silver.ref_tables", load_refs),
    ("silver.plate_lookup", build_plate_lookup),
    ("silver.registrations", rebuild("silver.registrations", REGISTRATIONS)),
    ("silver.policies", rebuild("silver.policies", POLICIES)),
    ("silver.theft_shredding", rebuild("silver.theft_shredding", THEFT)),
    ("silver.capture_log", rebuild("silver.capture_log", CAPTURES)),
]


def run(batch_id, as_of):
    """Rebuild every silver table. Returns (step, rows) for each step, and the share of
    camera reads (duplicates left out) that matched a registered vehicle."""
    conn = connect("silver")
    conn.autocommit = True                 # each rebuild is one TRUNCATE plus one INSERT ... SELECT
    cur = conn.cursor()
    results = []
    try:
        for step, build in STEPS:
            step_id = runlog.start_step(batch_id, step)
            try:
                rows = build(cur)
            except Exception:
                runlog.end_step(step_id, "FAILED")
                raise
            runlog.end_step(step_id, "OK", rows)
            results.append((step, rows))
        cur.execute("SELECT COUNT(*), SUM(read_status = 'MATCHED') FROM silver.capture_log WHERE is_duplicate = 0")
        reads, matched = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    return results, (int(matched or 0), reads)
