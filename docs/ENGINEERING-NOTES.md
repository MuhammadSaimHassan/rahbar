# Engineering notes

These answers describe the implementation and saved measurements as of 2026-11-07.
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

The fixture operation report captured `cpu: 180%/70%` and API memory of 48–56 MiB.
During this demonstration the tool temporarily pinned HPA bounds to three replicas,
then restored them. It proves metrics availability and continuity, not automatic
scale-out or real-model capacity. See `docs/evidence/operations.json`.

A better demand signal is queued work or in-flight requests per ready replica,
combined with generation latency and model-server saturation. This requires explicit
queue/concurrency instrumentation, Prometheus scraping, an external/custom metrics
adapter (or a queue-based scaler), and load testing of the inference service. Scaling
API pods alone should remain bounded by model throughput.

## 4. Indexer memory limit, observed memory and margin

`k8s/base/indexer-job.yaml:30` requests 256 MiB; line 31 limits memory to 1 GiB.
The CronJob uses the same settings at `k8s/base/reindex-cronjob.yaml:37`.
The real-corpus preprocessing run measured approximately 159 MiB parent-process
peak RSS with a warm OCR cache (`docs/evidence/indexer-validation.txt`). Subtracting
this from 1,024 MiB gives 865 MiB nominal headroom, about 84.5% of the limit.
This is not a measured whole-container safety margin: OCR/Poppler children,
cold extraction, embedding buffers and runtime overhead were not all represented.

The saved operational `kubectl top pods` sample was taken after the short fixture
Job completed, so it has no indexer row. Metrics-server samples can also miss a
short-lived peak. A production indexer cgroup peak and timed `kubectl top pods`
samples remain required; no Kubernetes indexer peak is invented here. Monitor during
the Job, retain container memory metrics, and inspect termination state with
`kubectl --context=rahbar -n rahbar describe pod <indexer-pod>`. Exceeding the cgroup
limit normally yields `OOMKilled` and exit 137; retrying the same limit does not fix it.

## 5. Where recall@5 is worst

The historical real-corpus baseline (`eval/baseline.json`, `by_type`) reports:

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
Without these checks, models with equal dimensions could silently rank vectors in
incompatible spaces; unequal dimensions would normally produce a store error.
To change models, build a matching index and coordinate the shared configuration;
an API restart alone cannot translate stored vectors.

## 7. The difficult failure and what the evidence supports

The clearest captured operational failure was an HTTP 502 during a rolling update,
despite `maxUnavailable: 0`. It would be tempting to interpret three replicas and
successful rollout status as proof of uninterrupted service. The traffic sampler
disproved that: `docs/evidence/operations-before-drain-fix.json` records one failure
in 174 requests. Endpoint removal and ingress propagation need time before the old
process exits; replica counts alone do not establish that drain interval.

`scripts/operational_demo.py` sends requests throughout rollout, rollback and
pod deletion. Increasing `preStop` to 15 seconds and total termination grace to
330 seconds (`k8s/base/api.yaml:21` and line 66) produced 135 successful samples
with zero failures in `docs/evidence/operations.json`. The follow-up run also waits
for metrics-server rather than treating an immediate `<unknown>` HPA sample as final.
These are finite fixture observations, not a guarantee under all real-model loads.

No retained timer proves that this incident took more than an hour, and no personal
student debugging history was supplied. This account records the observed symptom,
mistaken inference and diagnostic evidence; the assignment's personal duration and
experience requirement still needs the team's truthful confirmation.
