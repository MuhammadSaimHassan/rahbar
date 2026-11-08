# Real runtime operations

The run-real-operations label opts a same-repository dev PR into the hosted real
workflow. It uses a uniquely owned disposable minikube/Calico cluster and genuine
Ollama/Chroma/Redis. It does not modify local projects or an external deployment.

Checks: a working UI wget control and permitted API-to-Chroma request accompany a
UI-to-Chroma network timeout; Chroma Pod replacement must retain its PVC UID,
950-chunk count, catalog and metadata; a disposable wrong-model API probe must
remain live with explicit pin-mismatch readiness 503 and saved logs; a real CronJob
copy must publish a complete new generation under the same Nomic/768 pin while
sampled grounded traffic continues. The old answer cache must actually be warm.
Reports retain generations, cache keys and request outcomes, including failures.

The existing operational tool then checks three endpoints, rolling update,
rollback, Pod replacement, metrics and restoration. Its alternate tag refers to
the same image content: this demonstrates deployment mechanics, not compatibility
between different application versions. HPA bounds are temporarily fixed for the
experiment and restored. Singleton Chroma replacement is a recovery/persistence
test, not an assertion of zero downtime during that storage outage.

Status: pending actual hosted run. Requires PR #7 and #8; merge in order, with six
CI jobs and partner review. Preserve both real-runtime-operations.json and
real-rollout-rollback.json from the artifact, then remove the heavy opt-in label.

## First run and metrics follow-up

Run 42500255265 passed real Calico denial/controls, PVC recovery, explicit live pin
mismatch and real same-pin reindex continuity (95 successful sampled requests).
Rollout, rollback and Pod replacement also produced 337 successful requests with
zero failures and exact image/HPA restoration. The workflow still failed: HPA CPU
remained unknown within its original 90-second observation window, even though
kubectl top returned actual Pod metrics. The full failure is retained, not called
a complete passing operations run.

The follow-up restores the real HPA bounds before measurement and waits through
a bounded six-minute window for a numeric HPA reading. Kubernetes documents a
default five-minute CPU initialization period for new Pods:
https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/ .
This is an observation-window correction, not proof of the original root cause.
The test still fails if HPA metrics remain unknown and now retains HPA/controller
diagnostics. A new real run is required.

## Complete passing follow-up

[Run 42502474968](https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42502474968)
passed on source 4d961e9. All three reports (fresh acceptance, core operations and
rollout/rollback) are passed. Core evidence is now committed as
`evidence/real-runtime-operations.json`; rollout evidence is
`evidence/real-rollout-rollback.json`, with exact provenance in
`evidence/real-runtime-verification.json`. Earlier failures remain retained.

The run passed Calico denial plus positive controls, PVC UID/index preservation,
explicit wrong-model readiness 503 with liveness 200, and a same-Nomic/768 real
reindex that published a distinct complete generation with the same frozen hash.
All 119 reindex traffic samples passed. Rollout, rollback and Pod replacement had
342 successful samples and zero failures, with exact settings restoration.

The restored production HPA was min 3/max 8 and reported CPU 53% against 70%, with
three replicas. Its conditions were AbleToScale=True, ScalingActive=True with
ValidMetricFound, and ScalingLimited=False. Saved events show earlier missing or
unready-Pod metrics before recovery, not missing CPU requests. This validates the
observed recovery; it does not prove the old window was the only contributing cause.
`evidence/real-hpa.txt` retains the full conditions/events; `real-top-pods.txt`
records API 53–54m CPU and 58–62 MiB, Chroma 16m/55 MiB, Redis 12m/4 MiB and UI
1m/2 MiB. These are finite samples, not measured maximum loads.

The alternate image tag still denotes the same image content. Production requests,
limits, model pins and HPA bounds were not weakened to pass. The opt-in label is
removed after collecting this result so evidence commits run only normal CI.
