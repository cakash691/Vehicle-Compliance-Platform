"""
run_pipeline.py -- one nightly run of the warehouse pipeline.

    python3 run_pipeline.py                      # as_of = yesterday (what the nightly job runs)
    python3 run_pipeline.py --as-of 2026-11-04   # replay one simulated night

A run covers everything up to the end of its as_of day. It opens a batch in etl.batch,
runs the layers in order with quality checks after silver and after gold (pipeline/checks.py),
and closes the batch as SUCCESS or FAILED. If a run fails, fix the cause and run the same
command again: a failed bronze copy changes nothing, silver is rebuilt in full on every run,
and gold only adds what it doesn't have yet.
"""

import argparse
import sys
import time
from datetime import date, timedelta

import mysql.connector

from pipeline import checks, load_bronze, load_gold, load_silver, runlog


def parse_args():
    ap = argparse.ArgumentParser(description="Run the warehouse pipeline for one business date.")
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                    help="last day the run covers, YYYY-MM-DD (default: yesterday)")
    return ap.parse_args()


def report(layer, results):
    """One line per layer, plus a line for each warning."""
    warnings = [r for r in results if r[3] == "WARN"]
    passed = sum(1 for r in results if r[3] == "OK")
    note = f", {len(warnings)} warning" + ("s" if len(warnings) > 1 else "") if warnings else ""
    print(f"  checks after {layer}: {passed} passed{note}")
    for name, _, count, _, note in warnings:
        print(f"    WARN {name}: {count:,}" + (f" ({note})" if note else ""))


def main():
    as_of = parse_args().as_of
    if as_of >= date.today():
        sys.exit(f"as_of must be a finished day, before today ({date.today()}).")
    try:
        if not runlog.acquire_run_lock():
            sys.exit("Another run of the pipeline is still going. Wait for it to finish, then try again.")
        runlog.close_abandoned_batches()
        last = runlog.last_successful_as_of()
    except mysql.connector.Error as e:
        sys.exit(f"Cannot read the run log ({e.msg}).\n"
                 "Run the DDL files in mysql/etl, mysql/bronze, mysql/silver and mysql/gold first (see README).")
    if last is not None and as_of < last:
        sys.exit(f"The warehouse already covers up to {last}, so as_of {as_of} is in the past.\n"
                 "To replay from scratch, run mysql/etl/reset_warehouse.sql first.")

    batch_id = runlog.open_batch(as_of)
    print(f"Batch {batch_id}, as_of {as_of}")
    started = time.perf_counter()
    try:
        for source, rows, old_wm, new_wm in load_bronze.run(batch_id, as_of):
            print(f"  bronze <- {source:<31} {rows:>8,} rows   watermark {old_wm or '-'} -> {new_wm or '-'}")
        steps, (matched, reads) = load_silver.run(batch_id, as_of)
        for step, rows in steps:
            print(f"  {step:<41} {rows:>8,} rows")
        print(f"  camera reads matched to a vehicle: {matched:,} of {reads:,} ({100 * matched / max(1, reads):.1f}%)")
        report("silver", checks.run(batch_id, as_of, "silver"))     # a failure stops the night here
        steps, (registered, on_road) = load_gold.run(batch_id, as_of)
        for step, rows in steps:
            print(f"  {step:<41} {rows:>8,} rows")
        print(f"  uninsured on {as_of}: {100 * registered:.1f}% of registered vehicles, "
              f"{100 * on_road:.1f}% of those seen on camera in the last 90 days")
        report("gold", checks.run(batch_id, as_of, "gold"))
    except Exception as e:
        runlog.close_batch(batch_id, "FAILED", str(e)[:500])
        sys.exit(f"Batch {batch_id} FAILED: {e}\n"
                 "Fix the cause and run the same command again.")
    runlog.close_batch(batch_id, "SUCCESS")
    print(f"SUCCESS in {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
