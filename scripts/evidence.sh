#!/usr/bin/env bash
# Collects REAL evidence from your running deployment into results/. Run after `make up`.
#   scripts/evidence.sh loadtest | docker50 | readiness | hpa | rollout | recovery | coldstart | top | all
set -uo pipefail
mkdir -p results
HOST=${HOST:-http://localhost:8080}
LOCUST="python3 -m locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --host $HOST"
ts() { date -u +%FT%TZ; }

loadtest() {  # standard marking command; Locust exits 1 on any failure, which is fine
  $LOCUST --run-time 2m --csv results/loadtest 2>&1 | tee results/loadtest_console.log
}

top() {  # standard load test through the Ingress with exactly two Ready replicas, sampling kubectl top
  kubectl -n app scale deploy command-parser --replicas=2; kubectl -n app rollout status deploy/command-parser
  $LOCUST --run-time 2m --csv results/loadtest > results/loadtest_console.log 2>&1 &
  sleep 75; { echo "# $(ts) kubectl top pods (during load test)"; kubectl -n app top pods; } | tee results/kubectl_top_pods.log
  wait
}

docker50() {  # 50 sequential requests at 1 CPU / 1 GiB. Needs: kubectl -n data port-forward --address 0.0.0.0 svc/seaweedfs-s3 8333:8333
  . .secrets/s3.env
  docker rm -f cp-limit >/dev/null 2>&1
  docker run -d --name cp-limit --cpus=1.0 --memory=1g --memory-swap=1g -p 8000:8000 --add-host=host.docker.internal:host-gateway \
    -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e S3_ENDPOINT=http://host.docker.internal:8333 -e MAX_NEW_TOKENS=96 \
    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY command-parser:local >/dev/null
  { echo "# $(ts) docker run --cpus=1.0 --memory=1g command-parser:local"
    for t in $(seq 1 120); do rc=$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz); echo "healthz $(curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz) readyz $rc"; [ "$rc" = 200 ] && break; sleep 2; done
    ok=0; peak=0
    for i in $(seq 1 50); do
      code=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/parse -H 'content-type: application/json' -d '{"text":"what is the weather in london"}')
      mem=$(docker stats --no-stream --format '{{.MemUsage}}' cp-limit | awk '{print $1}')
      echo "request $i -> HTTP $code, mem $mem"; [ "$code" = 200 ] && ok=$((ok+1))
    done
    echo "ok=$ok/50"; docker stats --no-stream cp-limit
    echo "OOMKilled: $(docker inspect -f '{{.State.OOMKilled}}' cp-limit)"
    echo "peak memory (cgroup): $(docker exec cp-limit cat /sys/fs/cgroup/memory.peak 2>/dev/null || docker exec cp-limit cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)"
  } 2>&1 | tee results/docker_50req_limit_test.log
  docker rm -f cp-limit >/dev/null
}

readiness() {  # Service has no ready endpoints while the model is loading
  { echo "# $(ts) delete all pods, watch Service endpoints until the model has loaded"
    kubectl -n app delete pod -l app=command-parser --wait=false
    for i in $(seq 1 40); do
      echo "--- $(ts)"; kubectl -n app get endpoints command-parser-svc; kubectl -n app get pods -l app=command-parser
      curl -s -o /dev/null -w 'ingress /parse -> HTTP %{http_code}\n' -X POST $HOST/parse -H 'content-type: application/json' -d '{"text":"x"}'
      sleep 3
    done; } 2>&1 | tee results/readiness_gate.log
}

hpa() {
  { echo "# $(ts) HPA scaling test"; kubectl -n app get hpa; kubectl -n app scale deploy command-parser --replicas=1
    $LOCUST --run-time 6m --csv results/hpa_load > results/hpa_load_console.log 2>&1 &
    for i in $(seq 1 60); do echo "--- $(ts)"; kubectl -n app get hpa,pods; sleep 10; done; wait
    echo "# load finished, waiting for scale-down"
    for i in $(seq 1 40); do echo "--- $(ts)"; kubectl -n app get hpa,pods; sleep 15; done; } 2>&1 | tee results/hpa_scaling.log
}

rollout() {
  { echo "# $(ts) rolling update v1 -> v2 under load"; kubectl -n app scale deploy command-parser --replicas=2
    kubectl -n app rollout status deploy/command-parser
    LOADTEST_HEADERS_OUT=results/rollout_headers.json $LOCUST --run-time 4m --csv results/rollout > results/rollout_console.log 2>&1 &
    sleep 30
    kubectl -n app set env deploy/command-parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/
    kubectl -n app rollout status deploy/command-parser
    sleep 30; echo "# $(ts) rollback"; kubectl -n app rollout undo deploy/command-parser
    kubectl -n app rollout status deploy/command-parser; wait
    kubectl -n app rollout history deploy/command-parser
    curl -si -X POST $HOST/parse -H 'content-type: application/json' -d '{"text":"what is the weather in london"}' | grep -i -E 'HTTP/|x-model-version|x-served-by'
    tail -n 25 results/rollout_console.log; cat results/rollout_headers.json; } 2>&1 | tee results/rolling_update_rollback.log
}

recovery() {
  { echo "# $(ts) pod recovery under load"; kubectl -n app scale deploy command-parser --replicas=2; kubectl -n app rollout status deploy/command-parser
    LOADTEST_HEADERS_OUT=results/recovery_headers.json $LOCUST --run-time 3m --csv results/recovery > results/recovery_console.log 2>&1 &
    sleep 30; victim=$(kubectl -n app get pods -l app=command-parser -o name | head -1); echo "deleting $victim"; kubectl -n app delete "$victim" --wait=false
    for i in $(seq 1 20); do echo "--- $(ts)"; kubectl -n app get pods -l app=command-parser; sleep 5; done; wait
    tail -n 25 results/recovery_console.log; } 2>&1 | tee results/pod_recovery.log
}

coldstart() {
  { echo "# $(ts) cold start x3 (delete all pods; time = pod creationTimestamp -> Ready)"
    for run in 1 2 3; do
      kubectl -n app delete pod -l app=command-parser --wait=true; sleep 3
      kubectl -n app wait --for=condition=Ready pod -l app=command-parser --timeout=300s
      for p in $(kubectl -n app get pods -l app=command-parser -o name); do
        c=$(kubectl -n app get "$p" -o jsonpath='{.metadata.creationTimestamp}')
        r=$(kubectl -n app get "$p" -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}')
        echo "run $run $p created=$c ready=$r seconds=$(( $(date -d "$r" +%s) - $(date -d "$c" +%s) ))"
        kubectl -n app logs "$p" | grep -E 'downloaded|model ready'
      done
    done; } 2>&1 | tee results/cold_start_times.log
  echo "Take the median of the per-pod 'seconds' values (or the slowest pod per run) and state which you used."
}

case "${1:-all}" in
  loadtest) loadtest;; top) top;; docker50) docker50;; readiness) readiness;; hpa) hpa;;
  rollout) rollout;; recovery) recovery;; coldstart) coldstart;;
  all) readiness; coldstart; top; hpa; rollout; recovery; python3 scripts/cost.py;;
esac
