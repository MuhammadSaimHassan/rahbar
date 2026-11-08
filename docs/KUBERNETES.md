# Kubernetes runbook

All workloads use namespace `rahbar`. Commands explicitly select context `rahbar` so
they do not deploy into another project.

## Objects and security

The base defines three API replicas (HPA 3–8 at 70% CPU), one nginx UI, Chroma as a
single-replica StatefulSet with a per-pod PVC, Redis with AOF persistence on a PVC, an
initial dummy Job and a weekly Sunday 02:00 Asia/Karachi CronJob. Both Jobs share the
same image, command, arguments, resources and security settings. `Forbid` prevents
overlapping scheduled Jobs; operators must avoid overlapping manual Jobs too. The dev
overlay suspends scheduled runs.

Chroma's image configuration sets `persist_path: /data`. Redis uses `Recreate` updates
to avoid two writers sharing its ReadWriteOnce PVC. Four internal ClusterIP Services
expose the workloads; Chroma's Service is headless for its StatefulSet. Ingress routes
`/` to nginx and `/api` to the API on `rahbar.local`.

Every workload has a dedicated ServiceAccount without an API token mount, a numeric
non-root user, RuntimeDefault seccomp, dropped capabilities, no privilege escalation
and a read-only root filesystem. `/tmp` uses emptyDir; durable data uses PVCs.
Only the API can read the optional hosted key. The placeholder Secret is never applied.

## Permitted network paths

| Source | Destination | Port |
| --- | --- | --- |
| ingress-nginx controller | UI | TCP 8080 |
| ingress-nginx controller or UI | API | TCP 8000 |
| API or indexer | Chroma | TCP 8000 |
| API | Redis | TCP 6379 |
| All RAHBAR pods | kube-dns in kube-system | UDP/TCP 53 |

Other paths are denied. Calico must enforce these policies. Ingress labels must match
the minikube addon. Responses on allowed connections need no separate reverse rule.
The browser talks to Ingress; nginx does not proxy `/api`. During real embedding work,
resolve `host.minikube.internal` and add an API/indexer egress rule for that IP `/32` on
TCP 11434. The real-indexer overlay adds scoped indexer-to-Redis access for the writer lease,
catalog publication and cache invalidation.

## Probes and pin

Liveness never touches dependencies. Readiness makes bounded read-only collection/count
calls to Chroma and sends Redis PING. It compares collection metadata `embed_model` and
`dimension` with the API configuration. Empty/missing indexes, missing metadata, model
or dimension mismatch, and unavailable dependencies return 503. Checks run at startup
and on readiness requests, so a later Job can make an existing process ready. Logs report
state transitions and both sides of a mismatch. Operations use 2-second timeouts; the
readiness probe allows 12 seconds for the sequential dependency operations. A failed
dependency never kills a process via liveness. Readiness now reads the active collection
and generation from Redis; absent a catalog, it uses the bootstrap collection. A malformed
catalog or generation mismatch fails readiness. Redis uses `noeviction` to protect that
permanent catalog; it must not be flushed as a cache reset.

## Measurements and remaining deployment checks

The later k3d fixture operation report in evidence/operations.json contains real
`kubectl top pods`, three ready endpoint addresses, a CPU HPA percentage and successful
rollout/rollback/Pod replacement traffic samples. Those fixture measurements do not
establish Calico enforcement or production-model indexer peak memory.
Resource allocations remain provisional for cold production indexing. The dummy Job does not establish the real OCR pipeline's peak
memory. CPU-based HPA needs metrics-server and may stay low during model I/O waits.

After following the README apply order, capture actual output under `docs/evidence/`:

```bash
kubectl --context=rahbar -n rahbar get pods -o wide
kubectl --context=rahbar -n rahbar top pods
kubectl --context=rahbar -n rahbar get hpa
kubectl --context=rahbar -n rahbar get endpoints api
kubectl --context=rahbar -n rahbar logs job/indexer
```

Network block test (expected timeout and nonzero exit):

```bash
kubectl --context=rahbar -n rahbar exec deployment/ui -- \
  wget -T 3 -O /dev/null http://chroma:8000/api/v2/heartbeat
```

Pin mismatch test on a dedicated stub lab (save and restore the actual pin for a real deployment):

```bash
kubectl --context=rahbar -n rahbar patch configmap rahbar-config \
  --type=merge -p '{"data":{"EMBED_MODEL":"deliberately-wrong"}}'
kubectl --context=rahbar -n rahbar rollout restart deployment/api
kubectl --context=rahbar -n rahbar get pods -l app=api
# The strategy retains old ready replicas; the new replica stays unready.
# Inspect the new pod's logs to record the model conflict, then restore the pin.
kubectl --context=rahbar -n rahbar patch configmap rahbar-config \
  --type=merge -p '{"data":{"EMBED_MODEL":"dummy-768"}}'
kubectl --context=rahbar -n rahbar rollout restart deployment/api
kubectl --context=rahbar -n rahbar rollout status deployment/api --timeout=180s
```

Send repeated requests through Ingress while deleting an API pod, recording failures and
request IDs. Three endpoints alone do not prove in-flight requests survived. PVC
persistence and the Calico policy block still need acceptance evidence on the documented
minikube deployment. Fixture HPA and Pod continuity observations are saved separately.

## Transition to production indexing

The `real-indexer` overlay adds only the writer paths needed for publication: indexer to
Redis and indexer to the configured Ollama host on TCP 11434. The host IP is initially
the inert TEST-NET address `192.0.2.1/32`. No broad internet egress is opened. The initial
Job and weekly CronJob are suspended during setup. The real Job deadline is two hours;
the dummy Job retains its shorter deadline.

1. Build/load `rahbar-indexer:corpus-dev` with `make corpus-image` after hash verification.
2. Ensure host Ollama is reachable from minikube, listens on the intended interface and
   has `nomic-embed-text` pulled. The API still uses stub generation at this milestone.
3. Confirm the existing dummy Job completed, then delete that Job only; its Pod template
   is immutable. Preserve database PVCs.
4. Apply `k8s/overlays/real-indexer`, configure the exact host IP, and resume the new Job.

```bash
kubectl --context=rahbar -n rahbar get job indexer
# Only after confirming the bootstrap Job completed:
kubectl --context=rahbar -n rahbar delete job indexer
kubectl --context=rahbar apply -k k8s/overlays/real-indexer
minikube -p rahbar ssh "grep host.minikube.internal /etc/hosts"
```

Replace `YOUR_HOST_IP` in this patch with the actual address from the preceding command:

```bash
kubectl --context=rahbar -n rahbar patch networkpolicy indexer-to-ollama --type=json \
  -p='[{"op":"replace","path":"/spec/egress/0/to/0/ipBlock/cidr","value":"YOUR_HOST_IP/32"}]'
kubectl --context=rahbar -n rahbar patch job indexer --type=merge \
  -p='{"spec":{"suspend":false}}'
kubectl --context=rahbar -n rahbar logs -f job/indexer
kubectl --context=rahbar -n rahbar wait --for=condition=complete job/indexer --timeout=7200s
```

The first transition changes the model pin, so restart API replicas after publication to
load the new ConfigMap values. This is distinct from a same-model re-index demonstration:

```bash
kubectl --context=rahbar -n rahbar rollout restart deployment/api
kubectl --context=rahbar -n rahbar rollout status deployment/api --timeout=180s
kubectl --context=rahbar -n rahbar create job --from=cronjob/reindex manual-real-reindex-1
```

Subsequent same-model publication switches the catalog without an API restart. Do not
reapply the stub `make apply` target or run the dummy writer against a production setup.
The bootstrap pin-mismatch example above restores `dummy-768`; for a real setup restore
`nomic-embed-text` instead. CI/CD will later replace local image tags with commit SHAs.

## Enable host Ollama queries

For a fresh real deployment, use `k8s/overlays/real-query` in place of the
`real-indexer` overlay in the preceding setup. Rebuild and load the API and UI
images with their configured tags. Keep the indexing Job suspended until you
configure host egress, then publish the real index before sending queries.

Pull both configured models on the Ollama host.

```bash
ollama pull nomic-embed-text
ollama pull llama3.2:3b
```

Set the exact host IP on **both** Ollama egress policies. Substitute the address
discovered during the real indexing setup.

```bash
for policy in indexer-to-ollama api-to-ollama; do
  kubectl --context=rahbar -n rahbar patch networkpolicy "$policy" --type=json \
    -p='[{"op":"replace","path":"/spec/egress/0/to/0/ipBlock/cidr","value":"YOUR_HOST_IP/32"}]'
done
```

For an existing real deployment with a completed initial Job, render the query
overlay locally and apply the API egress policy and Ingress settings separately,
then update `RETRIEVER=chroma` and `LLM_PROVIDER=ollama-host` in the ConfigMap and
roll out the rebuilt API and UI images. Applying the entire overlay also reapplies
the suspended writer configuration and the placeholder egress addresses.
