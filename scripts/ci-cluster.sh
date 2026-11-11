#!/usr/bin/env bash
set -euo pipefail

cluster=rahbar-ci-${GITHUB_RUN_ID:-$$}
context=k3d-$cluster
port=${CI_INGRESS_PORT:-18086}
work=$(mktemp -d)
export KUBECONFIG="$work/kubeconfig"
report_dir=${REPORT_DIR:-"$work/reports"}
mkdir -p "$report_dir"
owned=false
cleanup() {
  status=$?
  if [[ "$owned" == true ]]; then
    if (( status != 0 )); then
      kubectl --context "$context" -n rahbar get pods,svc,ingress -o wide >&2 || true
      kubectl --context "$context" -n rahbar describe pods >&2 || true
      kubectl --context "$context" -n rahbar logs job/indexer --all-containers >&2 || true
    fi
    k3d cluster delete "$cluster" || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT

images=("${API_IMAGE:?}" "${UI_IMAGE:?}" "${INDEXER_IMAGE:?}")
for image in "${images[@]}"; do
  [[ "$image" =~ ^[a-z0-9./_-]+:[a-f0-9]{40}$ ]] || {
    echo "Expected an image tagged with a full commit SHA: $image" >&2
    exit 2
  }
done

if k3d cluster list "$cluster" --no-headers 2>/dev/null | grep -q .; then
  echo "Cluster $cluster already exists" >&2
  exit 2
fi
owned=true
k3d cluster create "$cluster" --image rancher/k3s:v1.35.5-k3s1 \
  --port "127.0.0.1:$port:80@loadbalancer" \
  --kubeconfig-update-default=false --kubeconfig-switch-context=false --timeout 180s
k3d kubeconfig get "$cluster" > "$KUBECONFIG"
# Stream into the single fixture node so a failed import stops the job.
docker save "${images[@]}" | docker exec -i "k3d-$cluster-server-0" \
  ctr --address /run/k3s/containerd/containerd.sock --namespace k8s.io images import -

# Replace only the three application image references in the rendered overlay.
kubectl kustomize k8s/overlays/ci > "$work/fixture.yaml"
python - "$work/fixture.yaml" "${images[@]}" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
replacements = dict(zip(("rahbar-api:dev", "rahbar-ui:dev", "rahbar-indexer:dev"), sys.argv[2:], strict=True))
documents = list(yaml.safe_load_all(path.read_text()))
seen = set()
for document in documents:
    template = document.get("spec", {})
    if document["kind"] == "CronJob":
        template = template["jobTemplate"]["spec"]
    for container in template.get("template", {}).get("spec", {}).get("containers", []):
        old = container["image"]
        if old in replacements:
            container["image"] = replacements[old]
            seen.add(old)
if seen != replacements.keys():
    raise SystemExit("Rendered overlay did not contain all three application images")
path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
PY

kubectl --context "$context" apply -f "$work/fixture.yaml"
kubectl --context "$context" -n rahbar wait --for=condition=complete job/indexer --timeout=300s
for deployment in api ui; do
  kubectl --context "$context" -n rahbar rollout status "deployment/$deployment" --timeout=240s
done

base="http://127.0.0.1:$port"
curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-connrefused \
  -H 'Host: rahbar.local' "$base/" -o "$report_dir/ingress.html"
grep -q RAHBAR "$report_dir/ingress.html"
python eval/run_eval.py --api "$base" --host rahbar.local --timeout 30 \
  --golden eval/fixtures/golden.fixture.yaml --baseline eval/fixtures/baseline.json \
  --out "$report_dir/fixture-results.json"
python scripts/check_fixture_answers.py "$report_dir/fixture-results.json"
