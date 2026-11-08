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
