# RAHBAR starter Makefile. `make` or `make help` lists the targets.
# Targets marked (needs yours) work once you have written the Dockerfiles or manifests.

SHELL := /bin/bash
NS ?= rahbar
PROFILE ?= rahbar
KUBE_CONTEXT ?= $(PROFILE)
TAG ?= dev
PY ?= python3
VENV ?= .venv
BIN := $(abspath $(VENV))/bin
# The Ingress address. On Linux this is the minikube IP. On macOS or Windows with the
# docker driver, run `minikube tunnel` in another terminal and use INGRESS_IP=127.0.0.1.
INGRESS_IP ?= $(shell minikube -p $(PROFILE) ip 2>/dev/null)
HOST ?= rahbar.local

.DEFAULT_GOAL := help
.PHONY: help install test lint dev cluster images corpus-image smoke-images golden-check operations failures apply secret index ask fetch eval eval-fixtures check

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

install: ## create .venv and install the api, indexer and tool dependencies
	$(PY) -m venv "$(VENV)"
	"$(BIN)/python" -m pip install -q --upgrade pip
	"$(BIN)/python" -m pip install -q -r api/requirements-dev.txt -r indexer/requirements-dev.txt

test: ## run api, indexer and corpus tests (no cluster, model or network)
	cd api && "$(BIN)/pytest" -q
	cd indexer && "$(BIN)/pytest" -q
	"$(BIN)/pytest" -q corpus/tests eval/tests

lint: ## ruff and mypy over everything in Python
	"$(BIN)/ruff" check api indexer eval corpus
	cd api && "$(BIN)/mypy" app
	cd indexer && "$(BIN)/mypy" pipeline

dev: ## run the API with stubs on http://localhost:8000, serving the chat UI too
	cd api && SERVE_UI_DIR=../ui RETRIEVER=stub LLM_PROVIDER=stub "$(BIN)/uvicorn" app.main:app --reload --port 8000

cluster: ## start minikube with Calico, then enable metrics-server and ingress
	minikube -p $(PROFILE) start --driver=docker --cni=calico --memory=6144 --cpus=4
	minikube -p $(PROFILE) addons enable metrics-server
	minikube -p $(PROFILE) addons enable ingress

images: ## build the three images and load them into minikube
	docker build -t rahbar-api:$(TAG) api
	docker build -t rahbar-indexer:$(TAG) indexer
	docker build -t rahbar-ui:$(TAG) ui
	minikube -p $(PROFILE) image load rahbar-api:$(TAG)
	minikube -p $(PROFILE) image load rahbar-indexer:$(TAG)
	minikube -p $(PROFILE) image load rahbar-ui:$(TAG)

smoke-images: ## check built images without a cluster or model
	$(PY) scripts/smoke_images.py --tag $(TAG)

corpus-image: ## build and load the self-contained production indexer with verified documents
	"$(BIN)/python" corpus/fetch.py --verify
	docker build --target with-corpus --build-context corpus_files=./corpus -f indexer/Dockerfile -t rahbar-indexer:corpus-$(TAG) indexer
	minikube -p $(PROFILE) image load rahbar-indexer:corpus-$(TAG)

apply: ## apply the dev overlay
	kubectl --context=$(KUBE_CONTEXT) apply -k k8s/overlays/dev

secret: ## create the LLM key Secret from the LLM_API_KEY variable; never from a file
	@test -n "$$LLM_API_KEY" || { echo "export LLM_API_KEY=... first"; exit 1; }
	kubectl --context=$(KUBE_CONTEXT) create secret generic rahbar-secret -n $(NS) \
	  --from-literal=LLM_API_KEY="$$LLM_API_KEY" --dry-run=client -o yaml | kubectl --context=$(KUBE_CONTEXT) apply -f -

index: ## run the indexer once, from the CronJob's template
	kubectl --context=$(KUBE_CONTEXT) create job --from=cronjob/reindex reindex-$$(date +%s) -n $(NS)
	@echo "watch it with: kubectl --context=$(KUBE_CONTEXT) get jobs -n $(NS) -w"

ask: ## ask through the Ingress: make ask Q="What CGPA puts a student on academic warning?"
	@curl -s -X POST "http://$(INGRESS_IP)/api/ask" -H "Host: $(HOST)" \
	  -H 'Content-Type: application/json' -d "$$(Q="$(Q)" $(PY) -c 'import json,os; print(json.dumps({"question": os.environ["Q"]}))')" \
	  | $(PY) -m json.tool

fetch: ## download the documents listed in corpus/sources.yaml
	"$(BIN)/python" corpus/fetch.py

eval: ## score eval/golden.yaml through the Ingress and apply the CI gate
	"$(BIN)/python" eval/run_eval.py --api "http://$(INGRESS_IP)" --host $(HOST)

golden-check: ## validate the source-authored benchmark and frozen hashes without network
	"$(BIN)/python" eval/prepare_golden.py --check-lock

eval-fixtures: ## score the CI fixture golden set against a running fixture API
	"$(BIN)/python" eval/run_eval.py --api http://localhost:8000 --golden eval/fixtures/golden.fixture.yaml --out /tmp/rahbar-fixture-results.json

check: ## run the submission checker
	$(PY) scripts/check_submission.py

operations: ## measure rollout, rollback, replicas and pod continuity in a named lab context
	@test -n "$(ALT_API_IMAGE)" || { echo "set ALT_API_IMAGE to an imported alternate image"; exit 1; }
	"$(BIN)/python" scripts/operational_demo.py --context "$(KUBE_CONTEXT)" --namespace "$(NS)" 	  --api "http://$(INGRESS_IP)" --host "$(HOST)" --image "$(ALT_API_IMAGE)" 	  --out docs/evidence/operations.json

failures: ## run a read-only failure case: make failures STAGE=pin
	@test -n "$(STAGE)" || { echo "set STAGE to extraction, chunking, pin or source"; exit 1; }
	PYTHONPATH=api:indexer:eval "$(BIN)/python" eval/failure_experiments.py "$(STAGE)" $(FAILURE_ARGS) 	  --out "docs/evidence/failure-$(STAGE).json"
