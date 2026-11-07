#!/bin/bash
# schedule_nightly.sh -- run the pipeline every night on a Mac, with launchd.
#
#   bash scripts/schedule_nightly.sh           install the job, or update it (runs at 00:05)
#   bash scripts/schedule_nightly.sh remove    remove it
#
# Why launchd rather than cron: a MacBook is usually asleep at midnight. cron skips a run it
# misses; launchd runs it as soon as the Mac wakes. (On a Linux server, use cron; see README.)
# The job runs scripts/run_nightly.sh, which writes its logs to logs/.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="local.vehicle-compliance.nightly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "remove" ]; then
    launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null || true
    rm -f "$PLIST"
    echo "Removed the nightly job."
    exit 0
fi

case "$REPO_DIR" in
    "$HOME/Desktop"* | "$HOME/Documents"* | "$HOME/Downloads"*)
        echo "macOS does not let scheduled jobs read ~/Desktop, ~/Documents or ~/Downloads,"
        echo "so the job would fail every night. Move the repo first, for example:"
        echo "    mkdir -p ~/Projects && mv \"$REPO_DIR\" ~/Projects/"
        exit 1 ;;
esac

mkdir -p "$REPO_DIR/logs" "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$REPO_DIR/scripts/run_nightly.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>0</integer>
        <key>Minute</key>
        <integer>5</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$REPO_DIR/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO_DIR/logs/launchd.log</string>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null || true      # drop the previous version, if any
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $PLIST"
echo "The pipeline now runs every night at 00:05, or as soon as the Mac wakes if it was asleep then."
echo "To run it once now:    launchctl kickstart $DOMAIN/$LABEL"
echo "To read the last log:  cat \"\$(ls -t $REPO_DIR/logs/pipeline_*.log | head -1)\""
