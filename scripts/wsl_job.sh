#!/usr/bin/env bash
# Runs DETACHED inside Ubuntu (as a systemd service started by wsl_launch.sh), so a dropped Windows console cannot stop it.
# Makes sure Docker, the cluster and Ollama are up, then runs the pipeline (finished stages are skipped). Exit 0 = finished, 3 = gave up.
set -uo pipefail
cd "$HOME/cs3081-kd-command-parser" || exit 3
mkdir -p results
rm -f results/job_exit.txt
# shellcheck disable=SC1091
. .venv/bin/activate
say() { printf '[%s] job: %s\n' "$(date +%H:%M:%S)" "$*"; }

say "started | $(uptime -p) | memory: $(free -m | awk '/Mem:/{print $3"/"$2" MB used"}')"
sudo -n dmesg 2>/dev/null | grep -iE 'out of memory|oom-kill|killed process' | tail -3 | sed 's/^/job: kernel log: /' || true

for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sudo -n systemctl start docker >/dev/null 2>&1 || true; sleep 3; done
docker info >/dev/null 2>&1 || { say "Docker is not running"; echo 3 > results/job_exit.txt; exit 3; }
k3d cluster start cs3081-cluster >/dev/null 2>&1 || true

ensure_ollama() {
  if curl -fs -m 5 localhost:11434/api/tags >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -qE '(0\.0\.0\.0|\*|\[::\]):11434'; then
    return 0
  fi
  say "starting Ollama on all interfaces"
  sudo -n systemctl disable --now ollama >/dev/null 2>&1 || true
  sudo -n pkill -x ollama >/dev/null 2>&1 || pkill -x ollama >/dev/null 2>&1 || true
  sleep 3
  OLLAMA_HOST=0.0.0.0 OLLAMA_NUM_PARALLEL=2 nohup ollama serve >> results/ollama_server.log 2>&1 &
  for _ in $(seq 1 60); do curl -fs -m 3 localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
}
ensure_ollama
ollama list 2>/dev/null | grep -q '^phi3.5' || ollama pull phi3.5

for attempt in 1 2 3; do
  if python scripts/run_all.py; then
    echo 0 > results/job_exit.txt
    say "FINISHED"
    exit 0
  fi
  say "run stopped (attempt $attempt/3); retrying in 60 s"
  sleep 60
  ensure_ollama
done
echo 3 > results/job_exit.txt
say "gave up: send the last 30 lines of results/pipeline_run.log"
exit 3
