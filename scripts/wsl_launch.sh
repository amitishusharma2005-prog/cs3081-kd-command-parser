#!/usr/bin/env bash
# Runs inside Ubuntu as your user (called by RUN_EVERYTHING.ps1).
# 1) copies/refreshes the project in ~/cs3081-kd-command-parser
# 2) starts the pipeline as a DETACHED job (survives a dropped Windows console) or re-attaches to the one already running
# 3) shows its log until it finishes.   Exit codes: 0 = finished OK, 3 = finished but failed, anything else = connection lost (the .ps1 reconnects)
set -uo pipefail
SRC="${1:?usage: wsl_launch.sh SOURCE_DIR}"
DEST="$HOME/cs3081-kd-command-parser"
UNIT=cs3081-run
if [ ! -d "$DEST" ]; then cp -r "$SRC" "$DEST"; else cp -rf "$SRC/scripts" "$SRC/setup_and_run.sh" "$DEST/"; fi
cd "$DEST" || exit 3
mkdir -p results

job_running() { systemctl is-active --quiet "$UNIT" 2>/dev/null || pgrep -f 'scripts/wsl_job\.sh' >/dev/null 2>&1; }

# first-ever run (nothing installed yet): the original interactive path, which needs a terminal for the GitHub login
if ! grep -q '"cluster": "done"' .pipeline_state.json 2>/dev/null && ! job_running; then
  bash setup_and_run.sh
  [ $? -eq 0 ] && exit 0 || exit 3
fi

LOGF="$DEST/results/job.log"
touch "$LOGF"
if job_running; then
  echo "A job is already running inside Ubuntu: re-attaching to it. ($(uptime -p))"
elif grep -q '"finalize": "done"' .pipeline_state.json 2>/dev/null; then
  echo "Everything is already finished."; [ -f 230103033.zip ] && exit 0 || exit 3
else
  echo "[$(date +%H:%M:%S)] launcher: starting the job detached (uptime: $(uptime -p))" >> "$LOGF"
  if ! sudo -n systemd-run --unit="$UNIT" --collect --uid="$(id -un)" --gid="$(id -gn)" --working-directory="$DEST" \
        --property=StandardOutput="append:$LOGF" --property=StandardError="append:$LOGF" \
        bash "$DEST/scripts/wsl_job.sh" >/dev/null 2>&1; then
    echo "systemd-run not available: falling back to a plain background process"
    setsid nohup bash "$DEST/scripts/wsl_job.sh" >> "$LOGF" 2>&1 < /dev/null &
  fi
  sleep 3
fi

tail -n 25 -F "$LOGF" &
TAILPID=$!
while job_running; do sleep 5; done
sleep 2; kill "$TAILPID" 2>/dev/null || true
rc="$(cat results/job_exit.txt 2>/dev/null || echo 3)"
[ "$rc" = "0" ] && exit 0 || exit 3
