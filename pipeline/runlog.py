"""
runlog.py -- the run log in the etl database.

etl.batch has one row per run of run_pipeline.py, and etl.step_log one row per step.
Log rows are written on their own connection and committed straight away, so they
survive even when the work of a failed step is rolled back.
"""

from db_config import connect

_conn = None


def _execute(sql, params=()):
    """Run one statement on the log connection; return (rows, last_insert_id)."""
    global _conn
    if _conn is None:
        _conn = connect("etl")
        _conn.autocommit = True
    cur = _conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall() if cur.with_rows else None
    last_id = cur.lastrowid
    cur.close()
    return rows, last_id


def acquire_run_lock():
    """Allow one run at a time. MySQL holds a named lock for as long as this connection lives,
    so a run that crashes never leaves the lock behind. False if another run holds it."""
    rows, _ = _execute("SELECT GET_LOCK('vehicle_compliance_pipeline', 0)")
    return rows[0][0] == 1


def close_abandoned_batches():
    """Batches still marked RUNNING belong to runs that died: we hold the lock, so none is alive."""
    _execute("UPDATE etl.batch SET status = 'FAILED', finished_at = NOW(), "
             "message = 'Abandoned: the run stopped before it finished' WHERE status = 'RUNNING'")


def last_successful_as_of():
    rows, _ = _execute("SELECT MAX(as_of) FROM etl.batch WHERE status = 'SUCCESS'")
    return rows[0][0]


def open_batch(as_of):
    _, batch_id = _execute(
        "INSERT INTO etl.batch (as_of, started_at, status) VALUES (%s, NOW(), 'RUNNING')", (as_of,))
    return batch_id


def close_batch(batch_id, status, message=None):
    _execute("UPDATE etl.batch SET status = %s, finished_at = NOW(), message = %s WHERE batch_id = %s",
             (status, message, batch_id))


def start_step(batch_id, step):
    _, step_id = _execute(
        "INSERT INTO etl.step_log (batch_id, step, status, started_at) VALUES (%s, %s, 'RUNNING', NOW())",
        (batch_id, step))
    return step_id


def end_step(step_id, status, rows_affected=None, message=None):
    _execute("UPDATE etl.step_log SET status = %s, rows_affected = %s, message = %s, finished_at = NOW() "
             "WHERE step_id = %s", (status, rows_affected, message, step_id))


def mark_rolled_back(step_ids):
    """Steps that finished but whose work was undone because a later step in the same transaction failed."""
    for step_id in step_ids:
        _execute("UPDATE etl.step_log SET status = 'ROLLED_BACK' WHERE step_id = %s", (step_id,))
