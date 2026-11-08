#!/usr/bin/env bash
# Runs only in an ephemeral GitHub-hosted VM, never against a developer's cluster.
set -Eeuo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted ]] || {
  echo "This runner script requires an ephemeral GitHub-hosted VM" >&2
  exit 2
}
: "${REPORT_DIR:?Set REPORT_DIR outside the checkout}"
mkdir -p "$REPORT_DIR"
report=$(realpath "$REPORT_DIR")
profile="rahbar-real-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
ollama="rahbar-real-ollama-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
monitor_pid=""
cluster_owned=false
ollama_owned=false
cleanup() {
  status=$?
  trap - EXIT
  set +e
  if [[ -n "$monitor_pid" ]]; then kill "$monitor_pid" 2>/dev/null; wait "$monitor_pid" 2>/dev/null; fi
  if [[ "$cluster_owned" == true ]]; then
    kubectl --context "$profile" -n rahbar get pods,svc,ingress,hpa,pvc -o wide > "$report/cluster-final.txt" 2>&1
    kubectl --context "$profile" -n rahbar describe pods > "$report/pod-diagnostics.txt" 2>&1
    kubectl --context "$profile" -n rahbar describe hpa > "$report/hpa-diagnostics.txt" 2>&1
    kubectl --context "$profile" -n kube-system logs -l component=kube-controller-manager --tail=150 > "$report/controller-diagnostics.txt" 2>&1
    kubectl --context "$profile" -n rahbar logs job/indexer > "$report/indexer.log" 2>&1
    kubectl --context "$profile" -n rahbar logs deployment/api --tail=150 > "$report/api.log" 2>&1
    minikube -p "$profile" delete > "$report/cluster-cleanup.txt" 2>&1
  fi
  if [[ "$ollama_owned" == true ]]; then
    docker logs "$ollama" > "$report/ollama.log" 2>&1
    docker rm -f "$ollama" > "$report/ollama-cleanup.txt" 2>&1
  fi
  printf '%s\n' "$status" > "$report/runner-exit-code.txt"
  exit "$status"
}
trap cleanup EXIT
{
  date -u -Is
  git rev-parse HEAD
  free -h
  df -h .
  docker version
  kubectl version --client
} > "$report/environment.txt"
python - <<'PY'
from pathlib import Path
mem = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))
if mem < 12 * 1024 * 1024:
    raise SystemExit('This real acceptance requires at least 12 GiB runner RAM')
PY
python eval/prepare_golden.py --check-lock
python corpus/fetch.py
python corpus/fetch.py --verify | tee "$report/corpus-verification.txt"
# Pin the cluster tool and verify its official checksum before execution.
work=$(mktemp -d)
version=v1.39.0
base="https://github.com/kubernetes/minikube/releases/download/$version"
curl --fail --location --retry 5 --retry-all-errors --retry-delay 3 --max-time 180 \
  "$base/minikube-linux-amd64" -o "$work/minikube"
curl --fail --location --retry 5 --retry-all-errors --retry-delay 3 --max-time 180 \
  "$base/minikube-linux-amd64.sha256" -o "$work/minikube.sha256"
expected=$(awk 'NR==1 {print $1}' "$work/minikube.sha256")
[[ "$expected" =~ ^[a-f0-9]{64}$ ]]
printf '%s  %s\n' "$expected" "$work/minikube" | sha256sum --check
sudo install -m 0755 "$work/minikube" /usr/local/bin/minikube
minikube version >> "$report/environment.txt"
# The original measured provider version; real vectors and real generation, no adapter.
docker run -d --name "$ollama" --memory=6g --cpus=3 \
  -p 0.0.0.0:11434:11434 \
  -e OLLAMA_HOST=0.0.0.0:11434 -e OLLAMA_KEEP_ALIVE=-1 \
  -e OLLAMA_MAX_LOADED_MODELS=2 -e OLLAMA_NUM_PARALLEL=1 \
  -e OLLAMA_CONTEXT_LENGTH=4096 ollama/ollama:0.6.5
ollama_owned=true
curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-all-errors \
  --retry-max-time 120 --connect-timeout 5 --max-time 10 \
  http://127.0.0.1:11434/api/version > "$report/ollama-version.json"
timeout 900s docker exec "$ollama" ollama pull nomic-embed-text
timeout 900s docker exec "$ollama" ollama pull llama3.2:3b
curl --fail --silent --show-error http://127.0.0.1:11434/api/tags > "$report/model-tags.json"
cluster_owned=true
minikube -p "$profile" start --driver=docker --cni=calico \
  --kubernetes-version=v1.35.5 --memory=6144 --cpus=4 --wait-timeout=600s
minikube -p "$profile" addons enable metrics-server
minikube -p "$profile" addons enable ingress
make images PROFILE="$profile"
docker build --target with-corpus --build-context corpus_files=./corpus \
  -f indexer/Dockerfile -t rahbar-indexer:corpus-dev indexer
minikube -p "$profile" image load rahbar-indexer:corpus-dev
# Only this ephemeral job owns the build cache.
docker builder prune --force >/dev/null
kubectl kustomize k8s/overlays/real-query > "$report/deployment.yaml"
# Instrument the genuine writer without changing extraction/embedding/publication.
python - "$report/deployment.yaml" <<'PY'
import sys
from pathlib import Path
import yaml
p = Path(sys.argv[1])
objects = list(yaml.safe_load_all(p.read_text()))
wrapper = r"""
python -m pipeline.run --report /tmp/real-preprocessing.json
result=$?
echo RAHBAR_INDEXER_REPORT_START
cat /tmp/real-preprocessing.json 2>/dev/null || true
echo
echo RAHBAR_INDEXER_REPORT_END
printf 'RAHBAR_INDEXER_CGROUP_PEAK_BYTES='
cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo unavailable
exit "$result"
"""
for obj in objects:
    if obj['kind'] == 'Job' and obj['metadata']['name'] == 'indexer':
        container = obj['spec']['template']['spec']['containers'][0]
        container['command'] = ['/bin/sh', '-c']
        container['args'] = [wrapper]
p.write_text(yaml.safe_dump_all(objects, sort_keys=False))
PY
kubectl --context "$profile" apply -f "$report/deployment.yaml"
kubectl --context "$profile" -n rahbar rollout status statefulset/chroma --timeout=600s
kubectl --context "$profile" -n rahbar rollout status deployment/redis --timeout=600s
host_ip=$(minikube -p "$profile" ssh 'getent hosts host.minikube.internal' | awk 'NR==1 {print $1}' | tr -d '\r')
python - "$host_ip" <<'PY'
import ipaddress
import sys
if not isinstance(ipaddress.ip_address(sys.argv[1]), ipaddress.IPv4Address):
    raise SystemExit('Expected an exact IPv4 inference-host address')
PY
for policy in indexer-to-ollama api-to-ollama; do
  kubectl --context "$profile" -n rahbar patch networkpolicy "$policy" --type=json \
    -p="[{\"op\":\"replace\",\"path\":\"/spec/egress/0/to/0/ipBlock/cidr\",\"value\":\"$host_ip/32\"}]"
done
kubectl --context "$profile" -n rahbar wait --for=jsonpath='{.status.phase}'=Running pods -l app=api --timeout=300s
kubectl --context "$profile" -n rahbar exec deployment/api -- python -c \
  'import httpx; r=httpx.get("http://host.minikube.internal:11434/api/tags", timeout=20, trust_env=False); r.raise_for_status(); print("Pod-to-host inference connection passed")' \
  | tee "$report/inference-connectivity.txt"
(
  while true; do
    date -u -Is
    kubectl --context "$profile" -n rahbar top pods -l job-name=indexer --containers || true
    sleep 5
  done
) > "$report/indexer-memory-samples.txt" 2>&1 &
monitor_pid=$!
kubectl --context "$profile" -n rahbar patch job indexer --type=merge -p '{"spec":{"suspend":false}}'
# Fail immediately on a failed Job instead of waiting two hours for Complete.
python - "$profile" <<'PYWAIT'
import json
import subprocess
import sys
import time
context = sys.argv[1]
deadline = time.monotonic() + 7200
while time.monotonic() < deadline:
    result = subprocess.run(['kubectl', '--context', context, '-n', 'rahbar',
                             'get', 'job', 'indexer', '-o', 'json'],
                            check=True, capture_output=True, text=True, timeout=30)
    job = json.loads(result.stdout)
    conditions = {c['type']: c for c in job.get('status', {}).get('conditions', [])
                  if c.get('status') == 'True'}
    if 'Complete' in conditions:
        break
    if 'Failed' in conditions or 'FailureTarget' in conditions:
        raise SystemExit('Production indexer Job failed: ' + str(conditions))
    time.sleep(5)
else:
    raise SystemExit('Production indexing exceeded its two-hour deadline')
PYWAIT
kill "$monitor_pid" 2>/dev/null || true
wait "$monitor_pid" 2>/dev/null || true
monitor_pid=""
kubectl --context "$profile" -n rahbar logs job/indexer > "$report/indexer.log"
kubectl --context "$profile" -n rahbar rollout status deployment/api --timeout=600s
kubectl --context "$profile" -n rahbar rollout status deployment/ui --timeout=600s
kubectl --context "$profile" -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=600s
ip=$(minikube -p "$profile" ip)
python scripts/check_real_acceptance.py --api "http://$ip" --context "$profile" \
  --out "$report/real-acceptance.json" --indexer-log "$report/indexer.log"

if [[ "${REAL_EVALUATION:-false}" == true ]]; then
  # Only this ephemeral run owns this Redis; remove answer cache, not the catalog.
  kubectl --context "$profile" -n rahbar exec deployment/api -- python -c \
    'import os,redis; r=redis.Redis.from_url(os.environ["REDIS_URL"]); keys=list(r.scan_iter(match="rahbar:cache:rahbar:*")); print("Removed initial warm answer cache keys:", r.unlink(*keys) if keys else 0)'
  python -u eval/run_eval.py --api "http://$ip" --host rahbar.local --timeout 300 \
    --out "$report/real-model-results.json" --checkpoint "$report/real-model-checkpoint.json"
fi

if [[ "${REAL_OPERATIONS:-false}" == true ]]; then
  PYTHONPATH=. python -u scripts/check_real_operations.py --api "http://$ip" \
    --context "$profile" --out "$report/real-runtime-operations.json"
  # A distinct reference of the same source-built image exercises rollout mechanics.
  docker tag rahbar-api:dev rahbar-api:acceptance-rollback
  minikube -p "$profile" image load rahbar-api:acceptance-rollback
  python -u scripts/operational_demo.py --context "$profile" --namespace rahbar \
    --api "http://$ip" --host rahbar.local --question \
    'What minimum CGPA avoids academic warning under the June 2026 rules?' \
    --request-timeout 300 --image rahbar-api:acceptance-rollback \
    --out "$report/real-rollout-rollback.json"
fi
