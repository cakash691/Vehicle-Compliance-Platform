"""
checks.py -- data quality checks, run by run_pipeline.py after silver and after gold.

Each check is one SQL query that counts the rows breaking a rule, so 0 means it passed. A query
may return a second column with a short note (what it measured, or which values are missing).

    ERROR  the rule must hold. After silver, a failure stops the night before gold changes:
           the checks are a gate. After gold, a failure marks the batch FAILED so someone looks:
           the checks are an alarm.
    WARN   worth knowing but no reason to stop. It is logged and the night carries on.

Every result is written to etl.step_log as a step named "check: ...", with the count and the note.
If a silver check fails, fix the cause (usually a parsing rule or a mapping in ref/) and run the
same night again: bronze still holds the night's rows, so nothing needs reloading.
"""

from datetime import timedelta

from db_config import connect
from pipeline import runlog


class CheckFailed(Exception):
    pass


SILVER = [
    ("registry: one current version per vehicle", "ERROR", """
        SELECT COUNT(*) FROM (SELECT chassis_no FROM silver.registrations
                              GROUP BY chassis_no HAVING SUM(is_current) <> 1) x"""),
    ("registry: no two vehicles share a plate", "ERROR", """
        SELECT COUNT(*) FROM (SELECT plate FROM silver.registrations WHERE is_current = 1 AND plate IS NOT NULL
                              GROUP BY plate HAVING COUNT(*) > 1) x"""),
    ("registry: every plate parses", "ERROR", """
        SELECT COUNT(*), GROUP_CONCAT(DISTINCT reg_no) FROM silver.registrations
        WHERE is_current = 1 AND plate IS NULL"""),
    ("registry: every vehicle class is in ref/vehicle_classes.csv", "ERROR", """
        SELECT COUNT(*), GROUP_CONCAT(DISTINCT vehicle_class) FROM silver.registrations WHERE vehicle_group IS NULL"""),
    ("policies: cover ends on or after it starts", "ERROR", """
        SELECT COUNT(*) FROM silver.policies WHERE valid_to < valid_from"""),
    ("policies: every insurer is in ref/insurers.csv", "WARN", """
        SELECT COUNT(*), GROUP_CONCAT(DISTINCT p.insurer) FROM silver.policies p
        WHERE NOT EXISTS (SELECT 1 FROM silver.ref_insurers r WHERE r.insurer_name = p.insurer)"""),
    ("theft cases: every case is tied to a vehicle", "WARN", """
        SELECT COUNT(*) FROM silver.theft_shredding WHERE chassis_no IS NULL"""),
    ("camera reads: none arrives before it was taken", "ERROR", """
        SELECT COUNT(*) FROM silver.capture_log WHERE ingested_at < capture_time"""),
    ("camera reads: bronze and silver hold the same reads", "ERROR", """
        SELECT ABS((SELECT COUNT(DISTINCT capture_id) FROM bronze.capture_log)
                   - (SELECT COUNT(*) FROM silver.capture_log))"""),
    # the reads gold is about to add; a sudden drop usually means a camera system changed its plate format
    ("camera reads: at least 90% of new reads match a vehicle", "ERROR", """
        SELECT IF(COUNT(*) > 0 AND SUM(c.read_status = 'MATCHED') < 0.9 * COUNT(*),
                  COUNT(*) - SUM(c.read_status = 'MATCHED'), 0),
               IF(COUNT(*) = 0, 'no new reads',
                  CONCAT(ROUND(100 * SUM(c.read_status = 'MATCHED') / COUNT(*), 1), '% of ', COUNT(*),
                         ' new reads matched a vehicle'))
        FROM silver.capture_log c
        WHERE c.is_duplicate = 0 AND NOT EXISTS (SELECT 1 FROM gold.fact_sighting f WHERE f.capture_id = c.capture_id)"""),
    ("camera reads: every camera is in ref/", "WARN", """
        SELECT COUNT(*), GROUP_CONCAT(c.camera_id) FROM (SELECT DISTINCT camera_id FROM silver.capture_log) c
        WHERE NOT EXISTS (SELECT 1 FROM silver.ref_toll_plazas t WHERE t.plaza_id = c.camera_id)
          AND NOT EXISTS (SELECT 1 FROM silver.ref_city_cameras k WHERE k.camera_id = c.camera_id)"""),
]

# fact -> its dimension keys: (column, dimension table, dimension key)
FACT_KEYS = {
    "fact_sighting": [("date_key", "dim_date", "date_key"), ("vehicle_key", "dim_vehicle", "vehicle_key"),
                      ("location_key", "dim_location", "location_key"), ("state_key", "dim_state", "state_key")],
    "fact_policy": [("vehicle_key", "dim_vehicle", "vehicle_key"), ("insurer_key", "dim_insurer", "insurer_key"),
                    ("state_key", "dim_state", "state_key"), ("issued_date_key", "dim_date", "date_key"),
                    ("valid_from_date_key", "dim_date", "date_key"), ("valid_to_date_key", "dim_date", "date_key")],
    "fact_theft_case": [("vehicle_key", "dim_vehicle", "vehicle_key"), ("state_key", "dim_state", "state_key"),
                        ("report_date_key", "dim_date", "date_key"), ("recovery_date_key", "dim_date", "date_key")],
    "fact_compliance_monthly": [("month_key", "dim_date", "date_key"), ("vehicle_key", "dim_vehicle", "vehicle_key"),
                                ("state_key", "dim_state", "state_key")],
}


def orphan_check(fact, keys):
    """Rows whose key finds no dimension row. The monthly snapshot is checked for the rows
    rebuilt tonight; its older months were checked on their own nights."""
    where = "f.dwh_batch_id = %(batch)s AND " if fact == "fact_compliance_monthly" else ""
    counts = [f"(SELECT COUNT(*) FROM gold.{fact} f WHERE {where}NOT EXISTS "
              f"(SELECT 1 FROM gold.{dim} d WHERE d.{dim_key} = f.{column}))" for column, dim, dim_key in keys]
    return (f"{fact}: every key finds its dimension row", "ERROR", "SELECT " + " + ".join(counts))


GOLD = [
    ("dim_vehicle: one current version per vehicle", "ERROR", """
        SELECT COUNT(*) FROM (SELECT chassis_no FROM gold.dim_vehicle GROUP BY chassis_no HAVING SUM(is_current) <> 1) x"""),
    ("dim_vehicle: each version starts the day after the previous one ends", "ERROR", """
        SELECT COUNT(*) FROM (
            SELECT valid_to, LEAD(valid_from) OVER (PARTITION BY chassis_no ORDER BY valid_from) AS next_from
            FROM gold.dim_vehicle) x
        WHERE (next_from IS NULL AND valid_to <> '9999-12-31')
           OR (next_from IS NOT NULL AND next_from <> valid_to + INTERVAL 1 DAY)"""),
    *[orphan_check(fact, keys) for fact, keys in FACT_KEYS.items()],
    ("fact_sighting: one row per silver read that is not a duplicate", "ERROR", """
        SELECT ABS((SELECT COUNT(*) FROM silver.capture_log WHERE is_duplicate = 0)
                   - (SELECT COUNT(*) FROM gold.fact_sighting))"""),
    ("fact_policy: one row per silver policy", "ERROR", """
        SELECT ABS((SELECT COUNT(*) FROM silver.policies) - (SELECT COUNT(*) FROM gold.fact_policy))"""),
    ("fact_theft_case: one row per silver case", "ERROR", """
        SELECT ABS((SELECT COUNT(*) FROM silver.theft_shredding) - (SELECT COUNT(*) FROM gold.fact_theft_case))"""),
    ("fact_compliance_monthly: a row for every vehicle this month", "ERROR", """
        SELECT ABS((SELECT COUNT(*) FROM gold.dim_vehicle
                    WHERE is_current = 1 AND vehicle_key <> -1 AND registration_date <= %(as_of)s)
                   - (SELECT COUNT(*) FROM gold.fact_compliance_monthly WHERE month_key = %(month)s))"""),
    ("fact_policy: policies still waiting for their vehicle", "WARN", """
        SELECT COUNT(*) FROM gold.fact_policy WHERE vehicle_key = -1"""),
    # a jump this large in one month usually means a feed went missing, not that behaviour changed
    ("fact_compliance_monthly: uninsured share within 5 points of last month", "WARN", """
        SELECT IF(ABS(cur - prev) > 5, 1, 0), CONCAT(cur, '% this month, ', prev, '% last month')
        FROM (SELECT ROUND(100 * AVG(CASE WHEN month_key = %(month)s THEN is_uninsured END), 1) AS cur,
                     ROUND(100 * AVG(CASE WHEN month_key = %(prev_month)s THEN is_uninsured END), 1) AS prev
              FROM gold.fact_compliance_monthly
              WHERE month_key IN (%(month)s, %(prev_month)s) AND status NOT IN ('STOLEN', 'SCRAPPED')) x"""),
]


def run(batch_id, as_of, layer):
    """Run the checks for a layer ("silver" or "gold") and log each one. Returns a list of
    (name, level, count, status, note). Raises CheckFailed if an ERROR check found any rows."""
    month = as_of.replace(day=1)
    previous = (month - timedelta(days=1)).replace(day=1)
    params = {"batch": batch_id, "as_of": as_of,
              "month": month.year * 10000 + month.month * 100 + 1,
              "prev_month": previous.year * 10000 + previous.month * 100 + 1}
    conn = connect("etl")
    cur = conn.cursor()
    results = []
    try:
        for name, level, sql in (SILVER if layer == "silver" else GOLD):
            step_id = runlog.start_step(batch_id, f"check: {name}")
            cur.execute(sql, params)
            row = cur.fetchone()
            count, note = int(row[0] or 0), (row[1] if len(row) > 1 else None)
            if isinstance(note, (bytes, bytearray)):              # some servers return text as bytes
                note = note.decode("utf-8", "replace")
            status = "OK" if count == 0 else ("FAILED" if level == "ERROR" else "WARN")
            runlog.end_step(step_id, status, count, None if note is None else str(note)[:255])
            results.append((name, level, count, status, note))
    finally:
        cur.close()
        conn.close()
    failed = [r for r in results if r[3] == "FAILED"]
    if failed:
        where = "after silver, so gold was not changed" if layer == "silver" else "after gold"
        lines = "; ".join(f"{name} ({count:,} rows{', ' + str(note) if note else ''})" for name, _, count, _, note in failed)
        raise CheckFailed(f"{len(failed)} check(s) failed {where}: {lines}")
    return results
