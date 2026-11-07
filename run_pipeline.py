"""
run_pipeline.py -- one nightly run of the warehouse pipeline.

    python3 run_pipeline.py                      # as_of = yesterday (what the nightly job runs)
    python3 run_pipeline.py --as-of 2026-11-04   # replay one simulated night

A run covers everything up to the end of its as_of day. It opens a batch in etl.batch,
runs the layers in order, and closes the batch as SUCCESS or FAILED. If a run fails,
fix the cause and run the same command again.

Only bronze exists so far; silver and gold slot in where marked below.
"""

import argparse
import sys
import time
from datetime import date, timedelta

import mysql.connector

from pipeline import load_bronze, runlog


def parse_args():
    ap = argparse.ArgumentParser(description="Run the warehouse pipeline for one business date.")
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                    help="last day the run covers, YYYY-MM-DD (default: yesterday)")
    return ap.parse_args()


def main():
    as_of = parse_args().as_of
    if as_of >= date.today():
        sys.exit(f"as_of must be a finished day, before today ({date.today()}).")
    try:
        last = runlog.last_successful_as_of()
    except mysql.connector.Error as e:
        sys.exit(f"Cannot read the run log ({e.msg}).\n"
                 "Run mysql/etl/ddl_etl.sql and mysql/bronze/ddl_bronze.sql first (see README).")
    if last is not None and as_of < last:
        sys.exit(f"The warehouse already covers up to {last}, so as_of {as_of} is in the past.\n"
                 "To replay from scratch, run mysql/etl/reset_warehouse.sql first.")

    batch_id = runlog.open_batch(as_of)
    print(f"Batch {batch_id}, as_of {as_of}")
    started = time.perf_counter()
    try:
        for source, rows, old_wm, new_wm in load_bronze.run(batch_id, as_of):
            print(f"  bronze <- {source:<31} {rows:>8,} rows   watermark {old_wm or '-'} -> {new_wm or '-'}")
        # load_silver.run(batch_id, as_of)   <- roadmap step 3
        # load_gold.run(batch_id, as_of)     <- roadmap step 4
    except Exception as e:
        runlog.close_batch(batch_id, "FAILED", str(e)[:500])
        sys.exit(f"Batch {batch_id} FAILED: {e}\n"
                 "Nothing was changed. Fix the cause and run the same command again.")
    runlog.close_batch(batch_id, "SUCCESS")
    print(f"SUCCESS in {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
