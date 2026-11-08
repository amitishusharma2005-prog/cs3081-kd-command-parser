#!/usr/bin/env bash
# Creates namespaces, generated S3 credentials and ConfigMaps. Nothing here is committed to Git.
set -euo pipefail
mkdir -p .secrets
if [ ! -f .secrets/s3.env ]; then
  printf 'AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' \
    "$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > .secrets/s3.env
fi
set -a; . .secrets/s3.env; set +a
for ns in data pipeline app; do kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -; done
for ns in data pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" --dry-run=client -o yaml | kubectl apply -f -
done
cat > .secrets/s3.json <<JSON
{"identities":[{"name":"admin","credentials":[{"accessKey":"$AWS_ACCESS_KEY_ID","secretKey":"$AWS_SECRET_ACCESS_KEY"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON
kubectl -n data create secret generic seaweedfs-s3-config --from-file=s3.json=.secrets/s3.json --dry-run=client -o yaml | kubectl apply -f -
kubectl -n data create configmap commands-pool --from-file=commands_pool.jsonl=data/commands_pool.jsonl --dry-run=client -o yaml | kubectl apply -f -
kubectl -n data create configmap seed-scripts --from-file=scripts/seed_buckets.py --from-file=scripts/seed_models.py --dry-run=client -o yaml | kubectl apply -f -
if [ -f models/v1/model.sha256 ] && [ -f models/v2/model.sha256 ]; then
  kubectl -n data create configmap model-checksums \
    --from-file=v1.sha256=models/v1/model.sha256 \
    --from-file=v2.sha256=models/v2/model.sha256 \
    --dry-run=client -o yaml | kubectl apply -f -
fi
