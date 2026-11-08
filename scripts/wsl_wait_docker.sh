#!/usr/bin/env bash
# Runs inside Ubuntu after a restart: wait until the Docker daemon answers.
for i in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then echo "docker is up"; exit 0; fi
  systemctl start docker >/dev/null 2>&1 || true
  sleep 3
done
echo "docker did not start"; systemctl status docker --no-pager | tail -15; exit 1
