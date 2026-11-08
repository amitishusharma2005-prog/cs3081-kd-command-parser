#!/usr/bin/env bash
# Runs INSIDE Ubuntu as root (called by RUN_EVERYTHING.ps1). Creates the user, enables systemd, installs Docker Engine.
set -euo pipefail
U="${1:?usage: wsl_bootstrap.sh USERNAME}"
export DEBIAN_FRONTEND=noninteractive
id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo "$U"
echo "$U ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$U"; chmod 440 "/etc/sudoers.d/90-$U"
printf '[boot]\nsystemd=true\n[user]\ndefault=%s\n' "$U" > /etc/wsl.conf
apt-get update -y
apt-get install -y ca-certificates curl git unzip python3 python3-pip python3-venv sudo
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
usermod -aG docker "$U"
systemctl enable docker >/dev/null 2>&1 || true
echo "bootstrap done"
