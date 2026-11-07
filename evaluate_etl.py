#!/usr/bin/env python3
"""
evaluate_etl.py -- score a vehicle_360 table or view against the ground-truth answer key.

Because the v2 data is simulated, the true status of every vehicle is known
(answer_key/vehicle_truth_2026-11-06.csv). This script compares what your ETL put in
vehicle_360 with that truth, so you can measure each improvement to the pipeline.

Run it after loading the base + all three daily drops and running your ETL:
    python3 evaluate_etl.py                       # the prototype's vehicle_dwh.vehicle_360
    python3 evaluate_etl.py --database gold       # the warehouse's gold.vehicle_360 view
    python3 evaluate_etl.py --password secret --user root

Status matching is by keyword, so it keeps working if you rename your status strings:
  contains "STOLEN" or "SHRED" -> STOLEN/SCRAPPED ; "EXPIRED" or "NO INSURANCE" or "UNINSURED" -> UNINSURED ;
  starts with "OK" or contains "CLEAR" -> CLEAR ; anything else -> OTHER.
"""
import argparse, csv, os
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--user", default="iia_app")
ap.add_argument("--password", default="iia_app_pw")
ap.add_argument("--database", default="vehicle_dwh", help="vehicle_dwh (prototype) or gold (warehouse)")
ap.add_argument("--truth", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "answer_key", "vehicle_truth_2026-11-06.csv"))
args = ap.parse_args()

import mysql.connector  # pip install mysql-connector-python

def etl_bucket(status):
    s = (status or "").upper()
    if "STOLEN" in s or "SHRED" in s: return "STOLEN/SCRAPPED"
    if "EXPIRED" in s or "NO INSURANCE" in s or "UNINSURED" in s: return "UNINSURED"
    if s.startswith("OK") or "CLEAR" in s: return "CLEAR"
    return "OTHER"

TRUTH_BUCKET = {"OK": "CLEAR", "EXPIRED": "UNINSURED", "NO_POLICY_IN_FEED": "UNINSURED", "STOLEN": "STOLEN/SCRAPPED", "SHREDDED": "STOLEN/SCRAPPED"}
truth = {r["canonical_plate"]: r for r in csv.DictReader(open(args.truth, encoding="utf-8"))}

conn = mysql.connector.connect(host=args.host, user=args.user, password=args.password, database=args.database)
cur = conn.cursor()
cur.execute("SELECT plate_canonical, status FROM vehicle_360")
rows = cur.fetchall()
cur.close(); conn.close()

matched, phantom = [], []
for plate, status in rows:
    (matched if plate in truth else phantom).append((plate, status))
seen_truth = {p for p, r in truth.items() if int(r["times_on_camera"]) > 0}
covered = seen_truth & {p for p, _ in matched}

labels = ["CLEAR", "UNINSURED", "STOLEN/SCRAPPED", "OTHER"]
cm = Counter((TRUTH_BUCKET[truth[p]["expected_status"]], etl_bucket(s)) for p, s in matched)
n = len(matched)
correct = sum(cm[(t, t)] for t in labels)
clear_total = sum(cm[("CLEAR", e)] for e in labels)
wrongly_flagged = clear_total - cm[("CLEAR", "CLEAR")]
unins_total = sum(cm[("UNINSURED", e)] for e in labels)
missed_unins = cm[("UNINSURED", "CLEAR")]
stolen_total = sum(cm[("STOLEN/SCRAPPED", e)] for e in labels)

print(f"vehicle_360 rows: {len(rows):,}")
print(f"  real registered plates : {n:,}")
print(f"  plates that do not exist (misreads, partial/empty reads, fake plates): {len(phantom):,}")
print(f"Registered vehicles seen on camera: {len(seen_truth):,}; present in vehicle_360 under their true plate: "
      f"{len(covered):,} ({100 * len(covered) / max(1, len(seen_truth)):.1f}%)\n")
print("Confusion matrix (rows = truth, columns = your ETL):")
print(f"{'':18}" + "".join(f"{l:>17}" for l in labels))
for t in labels[:3]:
    print(f"{t:18}" + "".join(f"{cm[(t, e)]:>17,}" for e in labels))
print(f"\nStatus accuracy on real plates: {100 * correct / max(1, n):.2f}%")
print(f"Insured vehicles wrongly flagged (would get a wrongful e-challan): {wrongly_flagged:,} of {clear_total:,} "
      f"({100 * wrongly_flagged / max(1, clear_total):.2f}%)")
print(f"Uninsured vehicles missed (marked clear): {missed_unins:,} of {unins_total:,} ({100 * missed_unins / max(1, unins_total):.2f}%)")
print(f"Stolen/scrapped vehicles caught: {cm[('STOLEN/SCRAPPED', 'STOLEN/SCRAPPED')]:,} of {stolen_total:,}")
false_stolen = sum(cm[(t, "STOLEN/SCRAPPED")] for t in ("CLEAR", "UNINSURED"))
print(f"Vehicles wrongly flagged as stolen/scrapped (e.g. already recovered): {false_stolen:,}")
if phantom:
    print(f"\nExamples of rows that are not real plates: {[p for p, _ in phantom[:8]]}")
