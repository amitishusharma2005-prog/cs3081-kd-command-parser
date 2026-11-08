# Fresh clone -> running system:   git clone <repo> && cd <repo> && make up
CLUSTER   := cs3081-cluster
IMAGE     := command-parser:local
WORKER_IMG := teacher-worker:local
SUBSET    ?=
VERSION   ?= v1

.PHONY: up down train test lint label clean-data evidence image

up:
	k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml
	bash scripts/secrets.sh
	kubectl apply -f cluster/seaweedfs.yaml
	kubectl -n data rollout status deploy/seaweedfs --timeout=300s
	kubectl -n data wait --for=condition=complete job/seed-buckets --timeout=300s
	kubectl apply -f cluster/seed-models.yaml
	kubectl -n data wait --for=condition=complete job/seed-models --timeout=600s
	$(MAKE) image
	kubectl apply -f cluster/app-deployment.yaml
	kubectl -n app rollout status deploy/command-parser --timeout=600s
	echo "Ready: curl -X POST http://localhost:8080/parse -H 'content-type: application/json' -d '{\"text\":\"what is the weather in london\"}'"

image:
	docker build -f service/Dockerfile -t $(IMAGE) .
	k3d image import $(IMAGE) -c $(CLUSTER)

down:
	k3d cluster delete $(CLUSTER)

# `make train` -> v1 (first 1,500 records); `make train SUBSET=50` smoke run; `make train VERSION=v2`
train:
	SUBSET=$(SUBSET) VERSION=$(VERSION) python3 training/train.py

# Task 1: run the two teacher workers (needs `OLLAMA_HOST=0.0.0.0 ollama serve` with phi3.5 pulled)
label:
	docker build -f worker/Dockerfile -t $(WORKER_IMG) .
	k3d image import $(WORKER_IMG) -c $(CLUSTER)
	kubectl apply -f cluster/pipeline-workers.yaml
	kubectl -n pipeline wait --for=condition=complete job/worker-0 job/worker-1 --timeout=36000s

clean-data:
	python3 worker/clean.py

lint:
	ruff check .

test:
	pytest -v tests
	python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check

evidence:
	scripts/evidence.sh all

.PHONY: all
all:
	python3 scripts/run_all.py
