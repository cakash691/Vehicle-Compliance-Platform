#!/bin/bash
# run_nightly.sh -- the nightly job: run the warehouse pipeline for yesterday and keep a log.
#
# A scheduler calls this (launchd on a Mac, see schedule_nightly.sh; cron on Linux), and you
# can also run it by hand. Each run appends to logs/pipeline_YYYY-MM-DD.log, named after the
# day it ran; logs older than 30 days are deleted. On a Mac, a failed run shows a notification.
# The exit code is the pipeline's: 0 when the batch succeeded.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 1
mkdir -p logs
LOG="logs/pipeline_$(date +%F).log"

# Schedulers start with a bare PATH, so use the project's virtual environment when there is one.
PYTHON="$REPO_DIR/venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

{
    echo "=== $(date '+%F %T') nightly run with $PYTHON"
    "$PYTHON" run_pipeline.py
} >> "$LOG" 2>&1
STATUS=$?

if [ "$STATUS" -ne 0 ] && command -v osascript > /dev/null; then
    osascript -e "display notification \"The nightly run failed. See $REPO_DIR/$LOG\" with title \"Vehicle Compliance Platform\"" || true
fi
find logs -name 'pipeline_*.log' -mtime +30 -delete 2> /dev/null
exit "$STATUS"
