"""
load_bronze.py -- copy new and changed source rows into bronze.

Bronze keeps an append-only copy of each source table: the source's columns, plus the
batch that copied the row (dwh_batch_id) and when (dwh_loaded_at). The sources overwrite
their own rows (an owner transfer replaces the registry row), so bronze is the only place
every version survives, and silver and gold can always be rebuilt from it.

Which rows: those whose change-tracking column is newer than the watermark (the newest
value copied so far) and no later than the end of the run's as_of day. Runs only cover
finished days, so a DATE column works the same way as a DATETIME one: by the time a day
is copied, all of its changes are in.

All four copies and the new watermarks are committed together. If anything fails, bronze
and the watermarks stay exactly as they were, and the run can simply be repeated.

All the databases live on one MySQL server here, so each copy is a single
INSERT ... SELECT. If a source moved to its own server, copy_new_rows() is the one
function that would change: fetch the rows over a second connection, then insert them.
"""

from datetime import timedelta

from db_config import connect
from pipeline import runlog

# source table, change-tracking column. The bronze table has the same name in `bronze`.
SOURCES = [
    ("rto_registration.registrations", "last_updated"),
    ("insurance.policies", "issued_at"),
    ("theft_records.theft_shredding", "updated_at"),
    ("roadcapture.capture_log", "ingested_at"),
]


def bronze_table(source):
    return "bronze." + source.split(".")[1]


def read_watermark(cur, source):
    cur.execute("SELECT watermark_value FROM etl.watermark WHERE source_table = %s", (source,))
    row = cur.fetchone()
    return row[0] if row else None


def check_not_reset(cur, source, column, watermark):
    """Stop if the source's newest row is older than what bronze already copied.
    That means the source was recreated, and copying would silently skip its rows."""
    if watermark is None:
        return
    cur.execute(f"SELECT MAX({column}) FROM {source}")
    (newest,) = cur.fetchone()
    if newest is None or str(newest) < watermark:
        raise RuntimeError(
            f"{source} looks reset: its newest {column} is {newest}, but bronze has already copied "
            f"up to {watermark}. To replay from scratch, run mysql/etl/reset_warehouse.sql first.")


def source_columns(cur, source):
    schema, table = source.split(".")
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, table))
    return [name for (name,) in cur.fetchall()]


def copy_new_rows(cur, source, column, watermark, as_of, batch_id):
    """Copy rows changed after the watermark, up to the end of as_of. Returns the row count.
    Columns are listed by name, so a column added to a source fails loudly here."""
    cols = ", ".join(f"`{c}`" for c in source_columns(cur, source))
    sql = (f"INSERT INTO {bronze_table(source)} ({cols}, dwh_batch_id, dwh_loaded_at) "
           f"SELECT {cols}, %s, NOW() FROM {source} WHERE {column} < %s")
    params = [batch_id, as_of + timedelta(days=1)]          # before midnight after as_of
    if watermark is not None:
        sql += f" AND {column} > %s"
        params.append(watermark)
    cur.execute(sql, params)
    return cur.rowcount


def newest_copied(cur, source, column, batch_id):
    cur.execute(f"SELECT MAX({column}) FROM {bronze_table(source)} WHERE dwh_batch_id = %s", (batch_id,))
    (newest,) = cur.fetchone()
    return None if newest is None else str(newest)


def run(batch_id, as_of):
    """Copy all four sources in one transaction. Returns (source, rows, old watermark, new watermark)."""
    conn = connect("bronze")
    cur = conn.cursor()
    results, done_steps = [], []
    try:
        for source, column in SOURCES:
            step_id = runlog.start_step(batch_id, bronze_table(source))
            try:
                watermark = read_watermark(cur, source)
                check_not_reset(cur, source, column, watermark)
                copied = copy_new_rows(cur, source, column, watermark, as_of, batch_id)
                newest = newest_copied(cur, source, column, batch_id)
                if newest is not None:                      # move the watermark only if rows came in
                    cur.execute("REPLACE INTO etl.watermark (source_table, watermark_column, watermark_value, batch_id) "
                                "VALUES (%s, %s, %s, %s)", (source, column, newest, batch_id))
                results.append((source, copied, watermark, newest or watermark))
            except Exception:
                runlog.end_step(step_id, "FAILED")
                raise
            runlog.end_step(step_id, "OK", copied)
            done_steps.append(step_id)
        conn.commit()                                       # copies and watermarks, all at once
    except Exception:
        conn.rollback()
        runlog.mark_rolled_back(done_steps)                 # their rows were undone too
        raise
    finally:
        cur.close()
        conn.close()
    return results
