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
uses `/healthz` for startup/liveness at `k8s/base/api.yaml:56` and line 60, and
`/readyz` for readiness at line 65.

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
`k8s/base/api.yaml:45`. Host Ollama performs inference outside these pods.
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

`k8s/base/indexer-job.yaml:30` begins the requests block (256 MiB); line 33
begins the limits block (1 GiB).
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
do not describe the whole workflow as green.

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
330 seconds (`k8s/base/api.yaml:21` and line 71) produced 135 successful samples
with zero failures in `docs/evidence/operations.json`. The follow-up run also waits
for metrics-server rather than treating an immediate `<unknown>` HPA sample as final.
These are finite fixture observations, not a guarantee under all real-model loads.

No retained timer proves that this incident took more than an hour, and no personal
student debugging history was supplied. This account records the observed symptom,
mistaken inference and diagnostic evidence; the assignment's personal duration and
experience requirement still needs the team's truthful confirmation.
