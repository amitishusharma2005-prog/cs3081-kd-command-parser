#!/usr/bin/env bash
# ONE command for Linux / WSL2-Ubuntu: installs everything that is missing, starts Ollama, then runs the whole project.
#   bash setup_and_run.sh
# Safe to re-run any time: finished work is skipped and long steps resume.
set -euo pipefail
cd "$(dirname "$0")"
REPO="amitishusharma2005-prog/cs3081-kd-command-parser"
say() { printf '\n=== %s ===\n' "$*"; }
mkdir -p results

say "1/7 Docker must be running (Docker Desktop with WSL integration)"
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not reachable. On Windows this should not happen (RUN_EVERYTHING.bat installs Docker Engine inside Ubuntu). Try: sudo systemctl start docker, then run this again."
  exit 1
fi

say "2/7 System packages"
sudo -v
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git unzip curl ca-certificates

say "3/7 k3d, kubectl, Ollama, GitHub CLI"
command -v k3d >/dev/null || curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
if ! command -v kubectl >/dev/null; then
  curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
fi
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
if ! command -v gh >/dev/null; then
  sudo mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y gh
fi

say "4/7 GitHub login and repository (a browser/code prompt appears only the first time)"
gh auth status >/dev/null 2>&1 || gh auth login -h github.com -p https -w -s repo,workflow,read:org
# pushing .github/workflows needs the 'workflow' scope, which the default login does not grant
gh auth status 2>&1 | grep -q workflow || gh auth refresh -h github.com -s workflow
gh auth setup-git
gh repo view "$REPO" >/dev/null 2>&1 || gh repo create "$REPO" --public
git config --global user.name "Amit Sharma"
git config --global user.email "amitishusharma2005@gmail.com"

say "5/7 Python environment"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -q --upgrade pip

say "6/7 Ollama (teacher phi3.5) listening on all interfaces so the cluster can reach it"
sudo systemctl stop ollama >/dev/null 2>&1 || true
pkill -x ollama >/dev/null 2>&1 || true
sleep 2
OLLAMA_HOST=0.0.0.0 OLLAMA_NUM_PARALLEL=2 nohup ollama serve > results/ollama_server.log 2>&1 &
for _ in $(seq 1 60); do curl -s localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
curl -s localhost:11434/api/tags >/dev/null || { echo "Ollama did not start; see results/ollama_server.log"; exit 1; }
ollama pull phi3.5

say "7/7 Running the whole project (labelling takes hours; Ctrl-C and re-run is safe)"
for attempt in 1 2 3; do
  if python scripts/run_all.py "$@"; then
    echo; echo "FINISHED. Your submission file: $(pwd)/230103033.zip"
    exit 0
  fi
  echo "Run stopped (attempt $attempt/3). Retrying in 30 s so temporary problems can clear..."; sleep 30
done
echo "Still failing: send the last 30 lines of results/pipeline_run.log to be fixed."
exit 1
