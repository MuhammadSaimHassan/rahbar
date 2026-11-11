# Engineering notes

These answers describe the implementation and saved measurements as of 2026-11-08.
Line references refer to this working tree. AI assistance is disclosed in AI-USAGE.md.

## 1. Indexing in API startup: three replicas, one index

Every rolling update would start several extraction/embedding jobs. Concurrent writers
could replace a collection another replica is querying, repeat expensive OCR and model
calls, and make startup depend on corpus availability. A bootstrap delete/recreate
writer would expose an empty or partial index. A PVC preserves files; it does not
serialize application writes.

The independent Job is declared at `k8s/base/indexer-job.yaml:2`; its writer command is
at line 25. The API's three replicas are at `k8s/base/api.yaml:6`. Its lifespan at
`api/app/main.py:31` creates services and checks dependencies without building an index.
The weekly writer has `concurrencyPolicy: Forbid` at
`k8s/base/reindex-cronjob.yaml:8`. Manual Jobs also share the real writer's Redis lease,
and publication switches a completed immutable generation (ADR 0002). Forbid alone
does not serialize manually created Jobs.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds

`api/app/routes/health.py:10` implements independent process liveness;
line 17 starts readiness, which calls the bounded dependency checker. The manifest
uses `/healthz` for startup/liveness at `k8s/base/api.yaml:50` and line 54, and
`/readyz` for readiness at line 59.

With the endpoints swapped, a live API would fail liveness while Chroma is slow.
Three failures at a 20-second probe interval can trigger a restart during the outage;
the 330-second termination grace means replacement is not necessarily immediate.
Readiness would incorrectly report success using process health, leaving unavailable
replicas eligible for traffic. All three replicas share the dependency, so restarting
them cannot repair it. Correct probes withdraw traffic on readiness failure and let
the processes recover after Chroma returns. This is a configuration analysis, not a
recorded 90-second outage experiment.

## 3. What the CPU HPA measures during generation

The HPA in `k8s/base/hpa.yaml` targets API CPU relative to requested CPU,
with 3–8 replicas and a 70% target. Each API requests 100m at
`k8s/base/api.yaml:44`. Host Ollama performs inference outside these pods.
Waiting on its HTTP response contributes little API CPU; extra API replicas do not
increase that model server's capacity. Embedding, validation and traffic handling
can consume CPU independently of generation latency.

The completed real operations run 42502474968 captured CPU **53%/70%**, three
replicas and API samples of **53–54m CPU / 58–62 MiB memory**. With each API
requesting 100m CPU, a 53m reading corresponds to 53% of that request. This explains
the denominator; it is not model-server CPU usage. See `docs/evidence/real-top-pods.txt`
and `real-hpa.txt`. The experiment temporarily fixed HPA bounds for deterministic
rollout testing, then restored the production 3–8 bounds before measuring HPA.
ScalingActive=True/ValidMetricFound proves the resource metric was usable. It does
not demonstrate automatic scale-out or an inference throughput limit.

A better demand signal is queued work or in-flight requests per ready replica,
combined with generation latency and model-server saturation. This requires explicit
queue/concurrency instrumentation, Prometheus scraping, an external/custom metrics
adapter (or a queue-based scaler), and load testing of the inference service. Scaling
API pods alone should remain bounded by model throughput.

## 4. Indexer memory limit, observed memory and margin

`k8s/base/indexer-job.yaml:30` requests 256 MiB; line 31 limits memory to 1 GiB.
The CronJob uses the same 1 GiB limit. The fresh production run
[42498284513](https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42498284513)
performed real OCR, extraction, embedding and publication of all 950 chunks from
nine verified sources in a Kubernetes Job. It used the unchanged production limit.

The Job's final cgroup `memory.peak` was **197,578,752 bytes (188.43 MiB)**.
The Python parent's `ru_maxrss` was separately **195,276,800 bytes (186.23 MiB)**.
The cgroup value accounts for the container's processes, rather than treating the
parent RSS as the entire OCR pipeline. A shell wrapper read the cgroup peak after
the real writer completed, before its container exited. Timestamped metrics-server
samples from `kubectl top pods -l job-name=indexer --containers` are saved in
`docs/evidence/real-indexer-memory-samples.txt`. Their highest observed memory was
151 MiB; sampling can
miss a transient peak, so it does not replace the cgroup high-water mark.

Relative to the 1,024 MiB limit, this run used **18.40%**, leaving **835.57 MiB
(81.60%) observed headroom**. It completed without an OOM. This is one cold-corpus
measurement, not a guarantee for larger documents, changed dependencies or parallel
OCR. Exceeding the cgroup limit normally yields OOMKilled/exit 137; repeating the
same workload with unchanged resources does not address that cause. The previous
159 MiB warm-cache parent-only report remains historical and is superseded for this
whole-container calculation. Exact output is in `docs/evidence/real-corpus-acceptance.json`.

## 5. Where recall@5 is worst

The fresh revised-prompt run (`eval/results.json`, `by_type`, run 42499897552)
reproduces the historical baseline retrieval figures:

| Question type | Questions | Recall@5 |
| --- | ---: | ---: |
| Ordinary | 10 | 90% |
| Version-sensitive | 4 | 75% |
| Exact-term | 3 | 100% |
| Injection | 1 | 100% |

The two abstentions have no relevant evidence and no recall denominator. Version
questions perform worst: similar wording appears across editions, while a short
condition or date changes the applicable rule. The explicit edition filter prevents
retired sources entering current answers, but cannot guarantee that the correct
clause ranks in the first five. Dense embeddings compress lexical details such as
clause identifiers and negation. Hybrid lexical/BM25 plus dense retrieval, followed
by metadata filtering and reranking, is the next retrieval improvement to evaluate.
It is not implemented. Exact-term questions happen to score best on this small sample;
the assignment's expected general weakness is not a reason to report different data.

The fresh run passed structural gates but answered only 6/18 answerable questions:
five covered the reference facts, one lab/theory conditional answer was incorrect,
and twelve returned fallback. All four version-sensitive and all three exact-term
questions fell back despite the retrieval figures above. Hence retrieval recall,
valid emitted citations and actual answer coverage are separate measurements. The
injection question was answered correctly without following the injected command.
No overall improvement over the earlier five complete answers is claimed. See
REAL-MODEL-EVALUATION.md and the AI-assisted per-question semantic review; team
review remains required.

## 6. Change EMBED_MODEL and restart only the API

`api/app/services/health.py:59` compares collection model/dimension to the API pin;
the mismatch message starts at line 61. Readiness returns 503, removes the replica
from ready endpoints and logs both configurations. Liveness stays healthy.
`api/app/retrieval/chroma.py:65` also verifies model, dimension and generation before
query embedding, protecting direct requests and changes between probes.

The controlled fixture experiment returned five hits normally, rejected the changed
pin with `Index metadata does not match the active catalog and embedding pin`, and
returned five after restoration (`docs/evidence/failure-pin.json`). The earlier
dependency smoke test separately recorded readiness 503 for a model mismatch.
The fresh real run 42500255265 also created a disposable API Pod with a deliberately
wrong EMBED_MODEL, while leaving the shared ConfigMap/index unchanged. Its /healthz
returned 200 and /readyz returned 503 with an explicit embedding_pin mismatch naming
both models and the common 768 dimension. Redis, index catalog and nonempty Chroma
checks remained ok. Its saved logs show the same mismatch. See
`docs/evidence/real-runtime-first-core.json`. The probe was removed afterwards;
this is an isolated reproduction of the API-only mismatch, not a coordinated model
migration. That run passed these core checks but its later HPA metric check failed;
do not describe that first whole workflow as green. The follow-up run
42502474968 passed all core operations and the HPA/rollout checks; its final
core evidence is in `docs/evidence/real-runtime-operations.json`.

Without these checks, models with equal dimensions could silently rank vectors in
incompatible spaces; unequal dimensions would normally produce a store error.
To change models, build a matching index and coordinate the shared configuration;
an API restart alone cannot translate stored vectors.

## 7. The failure: HPA metrics during real acceptance

This was an **AI-assisted project acceptance cycle**, not a claim of independent
student debugging. The first operational run began at **16:30:46 UTC**; the corrected
run's job completed at **17:31:11 UTC** on 8 November 2026. The recorded elapsed
cycle is **1 hour and 25 seconds**. It includes fresh environment creation, real
indexing/inference, test execution, diagnosis and waiting; it is not a timer of one
student's hands-on effort. Exact API timestamps are in
`docs/evidence/engineering-failure-timeline.json`. The team must review and understand
this account and keep the AI attribution accurate.

**Symptoms.** Calico denial/controls, PVC recovery, pin mismatch and same-model
reindexing passed. Rollout, rollback and Pod replacement also produced 337 successful
requests with zero failures. Nevertheless run 42500255265 failed because HPA CPU
still showed `<unknown>/70%`. A successful rollout or HTTP stream did not establish
that the autoscaler had usable CPU samples.

**The incorrect assumption.** The original tool assumed a 90-second window after
replacement was enough for HPA once Pod metrics were available. `kubectl top pods`
returned real API CPU/memory, yet `kubectl get hpa` still displayed unknown CPU.
Those are distinct observations. The tool correctly refused to call this complete.

**The diagnostic evidence.** `docs/evidence/real-rollout-first-metrics-failure.json`
records the unknown target, working top output and exact exception:
`resource metrics did not become available after pod replacement`.
The useful commands were:

```bash
kubectl --context <owned-real-context> -n rahbar top pods
kubectl --context <owned-real-context> -n rahbar get hpa
kubectl --context <owned-real-context> -n rahbar describe hpa
```

The follow-up describe output in `docs/evidence/real-hpa.txt` retains
`FailedGetResourceMetric` events saying metrics were missing or targeted Pods might
be unready, followed by `ScalingActive=True`, `ValidMetricFound` and CPU **53%/70%**.
This locates the failed observation in autoscaler metrics availability rather than
in RAG quality or a missing CPU request. Kubernetes documents a default five-minute
CPU initialization window: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/ .
That behavior is relevant to the bounded retry, not proof of a single exclusive cause.

**Correction and result.** `scripts/operational_demo.py` restores the real HPA
specification before the measurement and waits at most 360 seconds for a numeric
reading, retaining detailed HPA diagnostics if it still fails. This keeps the check;
it does not accept unknown metrics. The fresh rerun 42502474968 passed all checks:
119 grounded reindex samples and 342 rollout/rollback/replacement samples, with zero
sampled failures and no restore errors. HPA bounds were back to 3–8, with three
replicas and a valid 53% CPU reading. These are finite real-run observations, not
an uncached load guarantee or automatic scale-out demonstration.

The earlier fixture 502/drain incident is separately retained in
`operations-before-drain-fix.json` and `operations.json`; it motivated the existing
15-second preStop and 330-second termination grace. No unrecorded duration is assigned
to that older incident.
