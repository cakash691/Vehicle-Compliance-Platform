"""
load_gold.py -- build the star schema in gold from silver.

Gold keeps history and stable surrogate keys, so unlike silver it is never rebuilt. Each run
adds what silver has and gold does not have yet, matched on source ids (capture_id, policy_id,
chassis number plus change date), so a repeated or failed night is safe to run again. Each step
below commits as one transaction.

    dimensions  dim_date (filled once), dim_state, dim_location, dim_insurer,
                dim_vehicle (one row per version: SCD type 2)
    facts       fact_policy and fact_sighting (new rows added), fact_theft_case (rewritten),
                fact_compliance_monthly (current and previous month rebuilt)

Rule 8 of docs/DATA_MODEL.md, a vehicle's status on a date, is written once in status_sql()
and used by both facts that need it.
"""

from datetime import date, timedelta

from db_config import connect
from pipeline import runlog

SNAPSHOT_START = date(2023, 1, 1)                       # the insurer feed starts here (section 12)
DATE_RANGE = (date(2008, 1, 1), date(2035, 12, 31))     # registrations start 2008; 5-year covers run past 2030
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def key_of(day):
    """Python date -> YYYYMMDD integer key."""
    return day.year * 10000 + day.month * 100 + day.day


def date_key(column):
    """SQL for the YYYYMMDD key of a DATE or DATETIME column; -1 when it is NULL."""
    return f"COALESCE(YEAR({column}) * 10000 + MONTH({column}) * 100 + DAYOFMONTH({column}), -1)"


def status_sql(chassis, day, version):
    """Rule 8: a vehicle's status on a date. The first match wins. `version` is the alias of the
    dim_vehicle row valid on that date. Its registry status counts only from the day the registry
    recorded it (last_updated): a first version reaches back to 1900, so that date matters."""
    return f"""CASE
        WHEN {chassis} IS NULL THEN 'UNKNOWN'
        WHEN EXISTS (SELECT 1 FROM silver.theft_shredding t
                     WHERE t.chassis_no = {chassis} AND t.case_type = 'STOLEN' AND t.report_date <= {day}
                       AND (t.recovery_date IS NULL OR t.recovery_date > {day})) THEN 'STOLEN'
        WHEN ({version}.reg_status = 'SCRAPPED' AND {version}.last_updated <= {day})
          OR EXISTS (SELECT 1 FROM silver.theft_shredding t
                     WHERE t.chassis_no = {chassis} AND t.case_type = 'SCRAPPED' AND t.report_date <= {day}) THEN 'SCRAPPED'
        WHEN EXISTS (SELECT 1 FROM silver.policies p
                     WHERE p.chassis_no = {chassis} AND p.has_tp_cover = 1
                       AND p.valid_from <= {day} AND p.valid_to >= {day}) THEN 'INSURED'
        WHEN EXISTS (SELECT 1 FROM silver.policies p
                     WHERE p.chassis_no = {chassis} AND p.has_tp_cover = 1 AND p.valid_to < {day}) THEN 'EXPIRED'
        ELSE 'NO_POLICY' END"""


# ---------------------------------------------------------------- dimensions

def load_dim_date(cur, p):
    """Fill the calendar once, with a -1 row for "not yet / unknown"."""
    cur.execute("SELECT COUNT(*) FROM gold.dim_date")
    if cur.fetchone()[0]:
        return 0
    rows = [(-1, None, None, None, None, "Unknown", "n/a", "n/a", None, None)]
    day = DATE_RANGE[0]
    while day <= DATE_RANGE[1]:
        fy = day.year if day.month >= 4 else day.year - 1           # Indian financial year: April to March
        rows.append((key_of(day), day, day.year, (day.month - 1) // 3 + 1, day.month, MONTHS[day.month - 1],
                     f"{day.year}-{day.month:02d}", f"FY{fy}-{(fy + 1) % 100:02d}",
                     day.isoweekday(), int(day.isoweekday() >= 6)))
        day += timedelta(days=1)
    sql = ("INSERT INTO gold.dim_date (date_key, full_date, year, quarter, month, month_name, month_label, "
           "fiscal_year, day_of_week, is_weekend) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    for i in range(0, len(rows), 5000):
        cur.executemany(sql, rows[i:i + 5000])
    return len(rows)


UNKNOWN_ROWS = [
    "INSERT IGNORE INTO gold.dim_state (state_key, state_code, state_name) VALUES (-1, '??', 'Unknown')",
    "INSERT IGNORE INTO gold.dim_location (location_key, camera_id, camera_type, place_name, state_name) "
    "VALUES (-1, '-', 'UNKNOWN', 'Unknown camera', 'Unknown')",
    "INSERT IGNORE INTO gold.dim_insurer (insurer_key, insurer_name, current_company, sector) "
    "VALUES (-1, 'Unknown', 'Unknown', 'Unknown')",
    "INSERT IGNORE INTO gold.dim_vehicle (vehicle_key, chassis_no, last_updated, valid_from, valid_to, is_current, dwh_batch_id) "
    "VALUES (-1, '-', '1900-01-01', '1900-01-01', '9999-12-31', 1, 0)",
]


def load_unknown_rows(cur, p):
    """The -1 row of each dimension, which facts point at when nothing matches."""
    added = 0
    for sql in UNKNOWN_ROWS:
        cur.execute(sql)
        added += cur.rowcount
    return added


def load_dim_state(cur, p):
    cur.execute("UPDATE gold.dim_state d JOIN silver.ref_states r ON r.state_key = d.state_code "
                "SET d.state_name = r.state_name")
    cur.execute("""INSERT INTO gold.dim_state (state_code, state_name)
                   SELECT r.state_key, r.state_name FROM silver.ref_states r
                   WHERE NOT EXISTS (SELECT 1 FROM gold.dim_state d WHERE d.state_code = r.state_key)
                   ORDER BY r.state_key""")
    return cur.rowcount


# every camera that has sent a read, described as it reports itself, plus the city and
# NHAI traffic figure from ref/
CAMERAS = """(
    SELECT c.camera_id, c.camera_type, c.place_name, cc.city, c.state_name, c.latitude, c.longitude,
           tp.traffic_per_day
    FROM (SELECT camera_id, MIN(camera_type) AS camera_type, MIN(location) AS place_name,
                 COALESCE(MIN(capture_state), 'Unknown') AS state_name,
                 MIN(latitude) AS latitude, MIN(longitude) AS longitude
          FROM silver.capture_log GROUP BY camera_id) c
    LEFT JOIN silver.ref_city_cameras cc ON cc.camera_id = c.camera_id
    LEFT JOIN silver.ref_toll_plazas tp ON tp.plaza_id = c.camera_id
) cams"""


def load_dim_location(cur, p):
    cur.execute(f"""UPDATE gold.dim_location d JOIN {CAMERAS} ON cams.camera_id = d.camera_id
                    SET d.camera_type = cams.camera_type, d.place_name = cams.place_name, d.city = cams.city,
                        d.state_name = cams.state_name, d.latitude = cams.latitude, d.longitude = cams.longitude,
                        d.traffic_per_day = cams.traffic_per_day""")
    cur.execute(f"""INSERT INTO gold.dim_location (camera_id, camera_type, place_name, city, state_name,
                                                   latitude, longitude, traffic_per_day)
                    SELECT cams.camera_id, cams.camera_type, cams.place_name, cams.city, cams.state_name,
                           cams.latitude, cams.longitude, cams.traffic_per_day
                    FROM {CAMERAS}
                    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_location d WHERE d.camera_id = cams.camera_id)
                    ORDER BY cams.camera_id""")
    return cur.rowcount


def load_dim_insurer(cur, p):
    cur.execute("UPDATE gold.dim_insurer d JOIN silver.ref_insurers r ON r.insurer_name = d.insurer_name "
                "SET d.current_company = r.current_company, d.sector = r.sector")
    cur.execute("""INSERT INTO gold.dim_insurer (insurer_name, current_company, sector)
                   SELECT r.insurer_name, r.current_company, r.sector FROM silver.ref_insurers r
                   WHERE NOT EXISTS (SELECT 1 FROM gold.dim_insurer d WHERE d.insurer_name = r.insurer_name)
                   ORDER BY r.insurer_name""")
    return cur.rowcount


def load_dim_vehicle(cur, p):
    """SCD type 2. Add every registry version gold doesn't have yet (one per chassis and change
    date). A vehicle's first version starts on 1900-01-01, so earlier events still find it; a later
    version starts on its change date. Then close the previous versions of vehicles that changed."""
    cur.execute("""
        INSERT INTO gold.dim_vehicle (chassis_no, plate, vehicle_group, vehicle_class, body_type, maker, make_model,
            fuel_type, colour, transport_category, registration_date, rto_code, rto_name, state_name, owner_type,
            owner_name, owner_serial, reg_status, reg_valid_upto, last_updated, valid_from, valid_to, is_current,
            dwh_batch_id)
        SELECT r.chassis_no, r.plate, r.vehicle_group, r.vehicle_class, r.body_type, r.maker, r.make_model,
               r.fuel_type, r.colour, r.transport_category, r.registration_date, r.rto_code, r.rto_name,
               r.state_name, r.owner_type, r.owner_name, r.owner_serial, r.reg_status, r.reg_valid_upto,
               r.last_updated,
               IF(r.new_rank = 1 AND NOT EXISTS (SELECT 1 FROM gold.dim_vehicle d WHERE d.chassis_no = r.chassis_no),
                  '1900-01-01', r.last_updated),
               '9999-12-31', 1, %(batch)s
        FROM (
            SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.chassis_no ORDER BY s.last_updated) AS new_rank
            FROM silver.registrations s
            WHERE NOT EXISTS (SELECT 1 FROM gold.dim_vehicle d
                              WHERE d.chassis_no = s.chassis_no AND d.last_updated = s.last_updated)
        ) r
        ORDER BY r.chassis_no, r.last_updated""", p)
    added = cur.rowcount
    # each version ends the day before the next one starts; the last one is current
    cur.execute("""
        UPDATE gold.dim_vehicle d
        JOIN (SELECT vehicle_key, LEAD(valid_from) OVER (PARTITION BY chassis_no ORDER BY valid_from) AS next_from
              FROM gold.dim_vehicle
              WHERE chassis_no IN (SELECT chassis_no FROM gold.dim_vehicle GROUP BY chassis_no HAVING COUNT(*) > 1)
             ) n ON n.vehicle_key = d.vehicle_key
        SET d.valid_to = IF(n.next_from IS NULL, '9999-12-31', n.next_from - INTERVAL 1 DAY),
            d.is_current = (n.next_from IS NULL)""")
    return added


# ---------------------------------------------------------------- facts

def load_fact_policy(cur, p):
    # policies whose vehicle was missing from the registry get another try
    cur.execute("""DELETE f FROM gold.fact_policy f JOIN silver.policies s ON s.policy_id = f.policy_id
                   WHERE f.vehicle_key = -1
                     AND EXISTS (SELECT 1 FROM gold.dim_vehicle v WHERE v.chassis_no = s.chassis_no)""")
    cur.execute(f"""
        INSERT INTO gold.fact_policy (policy_id, policy_number, vehicle_key, insurer_key, state_key, issued_date_key,
            valid_from_date_key, valid_to_date_key, policy_type, has_tp_cover, cover_days, renewal_gap_days,
            filed_under_new, dwh_batch_id)
        SELECT s.policy_id, s.policy_number, COALESCE(v.vehicle_key, -1), COALESCE(i.insurer_key, -1),
               COALESCE(st.state_key, -1), {date_key('s.issued_at')}, {date_key('s.valid_from')},
               {date_key('s.valid_to')}, s.policy_type, s.has_tp_cover, DATEDIFF(s.valid_to, s.valid_from) + 1,
               NULL, s.filed_under_new, %(batch)s
        FROM silver.policies s
        LEFT JOIN gold.dim_vehicle v ON v.chassis_no = s.chassis_no
                                    AND DATE(s.issued_at) BETWEEN v.valid_from AND v.valid_to
        LEFT JOIN gold.dim_insurer i ON i.insurer_name = s.insurer
        LEFT JOIN gold.dim_state st ON st.state_name = v.state_name
        WHERE NOT EXISTS (SELECT 1 FROM gold.fact_policy f WHERE f.policy_id = s.policy_id)""", p)
    added = cur.rowcount
    # days without TP cover before each new TP policy: the gap after the vehicle's previous TP policy
    cur.execute("""
        UPDATE gold.fact_policy f
        JOIN (SELECT policy_id,
                     DATEDIFF(valid_from, LAG(valid_to) OVER (PARTITION BY chassis_no ORDER BY valid_from, policy_id)) - 1
                         AS gap
              FROM silver.policies WHERE has_tp_cover = 1) g ON g.policy_id = f.policy_id
        SET f.renewal_gap_days = GREATEST(0, g.gap)
        WHERE f.dwh_batch_id = %(batch)s""", p)
    return added


def load_fact_sighting(cur, p):
    # keep gold in step with silver: drop reads silver now calls duplicates, and give reads
    # that matched no vehicle before another try
    cur.execute("""DELETE f FROM gold.fact_sighting f JOIN silver.capture_log c ON c.capture_id = f.capture_id
                   WHERE c.is_duplicate = 1 OR (f.vehicle_key = -1 AND c.chassis_no IS NOT NULL)""")
    cur.execute(f"""
        INSERT INTO gold.fact_sighting (capture_id, date_key, capture_time, vehicle_key, location_key, state_key,
            plate_read, read_status, status_at_sighting, is_uninsured, camera_vehicle_type, ocr_confidence,
            ingested_at, dwh_batch_id)
        SELECT x.capture_id, x.date_key, x.capture_time, x.vehicle_key, x.location_key, x.state_key, x.plate_read,
               x.read_status, x.status, x.status IN ('EXPIRED', 'NO_POLICY'), x.vehicle_type, x.ocr_confidence,
               x.ingested_at, %(batch)s
        FROM (
            SELECT c.capture_id, {date_key('c.capture_time')} AS date_key, c.capture_time,
                   COALESCE(v.vehicle_key, -1) AS vehicle_key, COALESCE(l.location_key, -1) AS location_key,
                   COALESCE(st.state_key, -1) AS state_key, COALESCE(c.plate, c.plate_no, '') AS plate_read,
                   c.read_status, c.vehicle_type, c.ocr_confidence, c.ingested_at,
                   {status_sql('c.chassis_no', 'DATE(c.capture_time)', 'v')} AS status
            FROM silver.capture_log c
            LEFT JOIN gold.dim_vehicle v ON v.chassis_no = c.chassis_no
                                        AND DATE(c.capture_time) BETWEEN v.valid_from AND v.valid_to
            LEFT JOIN gold.dim_location l ON l.camera_id = c.camera_id
            LEFT JOIN gold.dim_state st ON st.state_name = c.capture_state
            WHERE c.is_duplicate = 0
              AND NOT EXISTS (SELECT 1 FROM gold.fact_sighting f WHERE f.capture_id = c.capture_id)
        ) x""", p)
    return cur.rowcount


def load_fact_theft_case(cur, p):
    """Accumulating snapshot: rewrite every case, so status, recovery and sightings stay current."""
    cur.execute(f"""
        REPLACE INTO gold.fact_theft_case (case_id, reference_no, case_type, case_status, vehicle_key, state_key,
            report_date_key, recovery_date_key, days_to_recovery, sightings_after_report, dwh_batch_id)
        SELECT t.case_id, t.reference_no, t.case_type, t.case_status, COALESCE(v.vehicle_key, -1),
               COALESCE(st.state_key, -1), {date_key('t.report_date')}, {date_key('t.recovery_date')},
               DATEDIFF(t.recovery_date, t.report_date),
               (SELECT COUNT(*) FROM gold.fact_sighting f
                JOIN gold.dim_vehicle fv ON fv.vehicle_key = f.vehicle_key
                WHERE fv.chassis_no = t.chassis_no AND f.capture_time >= t.report_date
                  AND (t.case_type = 'SCRAPPED' OR t.recovery_date IS NULL OR f.capture_time < t.recovery_date)),
               %(batch)s
        FROM silver.theft_shredding t
        LEFT JOIN gold.dim_vehicle v ON v.chassis_no = t.chassis_no AND t.report_date BETWEEN v.valid_from AND v.valid_to
        LEFT JOIN gold.dim_state st ON st.state_name = t.state_name""", p)
    cur.execute("SELECT COUNT(*) FROM gold.fact_theft_case")
    return cur.fetchone()[0]


MONTHLY = f"""
    INSERT INTO gold.fact_compliance_monthly (month_key, vehicle_key, state_key, status_as_of, status, is_uninsured,
        days_since_cover_ended, vehicle_age_years, sightings_in_month, dwh_batch_id)
    SELECT x.month_key, x.vehicle_key, x.state_key, x.as_of_day, x.status, x.status IN ('EXPIRED', 'NO_POLICY'),
           IF(x.status = 'EXPIRED', DATEDIFF(x.as_of_day, x.last_cover_end), NULL),
           x.vehicle_age_years, x.sightings, %(batch)s
    FROM (
        SELECT m.month_key, m.as_of_day, v.vehicle_key, COALESCE(st.state_key, -1) AS state_key,
               TIMESTAMPDIFF(YEAR, v.registration_date, m.as_of_day) AS vehicle_age_years,
               {status_sql('v.chassis_no', 'm.as_of_day', 'v')} AS status,
               (SELECT MAX(p.valid_to) FROM silver.policies p
                WHERE p.chassis_no = v.chassis_no AND p.has_tp_cover = 1 AND p.valid_to < m.as_of_day) AS last_cover_end,
               (SELECT COUNT(*) FROM gold.dim_vehicle dv
                JOIN gold.fact_sighting f ON f.vehicle_key = dv.vehicle_key
                                         AND f.date_key BETWEEN m.month_key AND m.month_key + 30
                WHERE dv.chassis_no = v.chassis_no) AS sightings       -- reads of any version of the vehicle
        FROM (SELECT date_key AS month_key, LEAST(LAST_DAY(full_date), %(as_of)s) AS as_of_day
              FROM gold.dim_date
              WHERE DAYOFMONTH(full_date) = 1 AND full_date BETWEEN %(first_month)s AND %(as_of)s) m
        JOIN gold.dim_vehicle v ON v.vehicle_key <> -1 AND v.registration_date <= m.as_of_day
                               AND m.as_of_day BETWEEN v.valid_from AND v.valid_to
        LEFT JOIN gold.dim_state st ON st.state_name = v.state_name
    ) x"""


def load_fact_compliance_monthly(cur, p):
    """Periodic snapshot. Rebuild from the month before the latest one stored (all months on the
    first run) up to the as_of month; older months are final."""
    cur.execute("SELECT MAX(month_key) FROM gold.fact_compliance_monthly")
    (latest,) = cur.fetchone()
    if latest is None:
        first = SNAPSHOT_START
    else:
        year, month = latest // 10000, latest // 100 % 100
        first = max(SNAPSHOT_START, date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1))
    months = {**p, "first_month": first, "first_month_key": key_of(first)}
    cur.execute("DELETE FROM gold.fact_compliance_monthly WHERE month_key >= %(first_month_key)s", months)
    cur.execute(MONTHLY, months)
    return cur.rowcount


STEPS = [
    ("gold.dim_date", load_dim_date),
    ("gold.unknown_rows", load_unknown_rows),
    ("gold.dim_state", load_dim_state),
    ("gold.dim_location", load_dim_location),
    ("gold.dim_insurer", load_dim_insurer),
    ("gold.dim_vehicle", load_dim_vehicle),
    ("gold.fact_policy", load_fact_policy),
    ("gold.fact_sighting", load_fact_sighting),
    ("gold.fact_theft_case", load_fact_theft_case),
    ("gold.fact_compliance_monthly", load_fact_compliance_monthly),
]


def uninsured_shares(cur, as_of):
    """Share of vehicles without TP cover on as_of (stolen and scrapped left out): of all registered
    vehicles, and of those seen on camera in the 90 days up to as_of."""
    month = key_of(as_of.replace(day=1))
    cur.execute("SELECT AVG(is_uninsured) FROM gold.fact_compliance_monthly "
                "WHERE month_key = %s AND status NOT IN ('STOLEN', 'SCRAPPED')", (month,))
    registered = cur.fetchone()[0]
    cur.execute("""SELECT AVG(m.is_uninsured)
                   FROM gold.fact_compliance_monthly m JOIN gold.dim_vehicle v ON v.vehicle_key = m.vehicle_key
                   WHERE m.month_key = %s AND m.status NOT IN ('STOLEN', 'SCRAPPED')
                     AND v.chassis_no IN (SELECT dv.chassis_no FROM gold.fact_sighting f
                                          JOIN gold.dim_vehicle dv ON dv.vehicle_key = f.vehicle_key
                                          WHERE f.vehicle_key <> -1 AND f.date_key BETWEEN %s AND %s)""",
                (month, key_of(as_of - timedelta(days=90)), key_of(as_of)))
    on_road = cur.fetchone()[0]
    return float(registered or 0), float(on_road or 0)


def run(batch_id, as_of):
    """Run every gold step, each as one transaction. Returns (step, rows) for each step, and the
    uninsured shares on as_of."""
    conn = connect("gold")
    cur = conn.cursor()
    params = {"batch": batch_id, "as_of": as_of}
    results = []
    try:
        for step, load in STEPS:
            step_id = runlog.start_step(batch_id, step)
            try:
                rows = load(cur, params)
                conn.commit()
            except Exception:
                conn.rollback()
                runlog.end_step(step_id, "FAILED")
                raise
            runlog.end_step(step_id, "OK", rows)
            results.append((step, rows))
        shares = uninsured_shares(cur, as_of)
    finally:
        cur.close()
        conn.close()
    return results, shares
