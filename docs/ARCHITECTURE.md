# Architecture

The static nginx UI sends questions through Ingress `/api` to three FastAPI replicas.
The API validates input, resolves one immutable index generation, embeds the question,
retrieves filtered passages, checks the shared answer cache, generates on a miss,
validates grounding references, and returns the public answer. API startup never
extracts documents, creates collections or writes vectors.

## State ownership

| Component | Kubernetes object | State and role |
| --- | --- | --- |
| API | Deployment, HPA 3–8 | Read-only Chroma access; Redis answer cache; no indexing |
| Indexer | Job, weekly CronJob | Sole Chroma writer; extraction through publication |
| Chroma | Single StatefulSet, volumeClaimTemplates | Durable vector index, stable identity and claim |
| Redis | Deployment with Recreate, PVC, AOF | Active catalog, writer lease and expiring answer cache |
| UI | Deployment | Static browser interface; no database access |

Chroma's StatefulSet preserves the claim associated with `chroma-0` during replacement.
A headless ClusterIP Service provides discovery. One replica and one claim do not
provide database high availability, and scaling this StatefulSet does not establish
safe shared-index replication. Redis uses Recreate to avoid concurrent instances
writing the same persisted data. Its `noeviction` policy protects essential catalog
metadata; failed cache writes are best effort. Both stores are internal ClusterIP
services and require backup planning beyond this coursework deployment.

## Publication and request consistency

The indexer writes a fresh collection, verifies count/metadata and atomically publishes
a Redis catalog pointer under a renewed writer lease. Failed staging leaves the old
catalog active. Readers retain a single generation for retrieval and cache operations;
previous collections stay available for in-flight requests. Publication invalidates
previous-generation cache keys. New requests cannot reuse old-generation answers even
if an earlier request writes its answer after publication. Cleanup of old collections
is deliberate and currently manual. See ADRs 0001 and 0002.

## Retrieval, generation and cache

Real queries use Chroma HTTP with normalized 768-dimensional Nomic vectors from host
Ollama. Document inputs use `search_document:`, queries `search_query:`. Metadata
checks enforce model, dimension and generation. Current queries exclude superseded
sources; explicit historical requests select the supported edition. A 0.70 relevance
floor separates absent-topic and relevant scores on the small frozen benchmark.

Redis caching happens after retrieval so a hit can be checked against this request's
evidence. Keys isolate generation, evidence IDs, edition, endpoint/provider/model,
temperature and prompt revision. Up to 32 candidates are checked using cosine 0.85
plus numeric and polarity guards. Follow-ups, abstentions, failed validations and
fallbacks are not cached. The measured guarded test achieved zero false hits but
reused only one of six equivalent paraphrases (ADR 0003).

The Ollama and optional HTTPS hosted generators share a delimited evidence prompt
and strict Answer schema. Validation rejects unsupported citations and invalid inline
markers, retries once, then returns a safe fallback. Citation validity does not prove
semantic entailment: the historical real model reversed one lab/theory condition.
Hosted mode transfers questions/passages to the configured provider; ADR 0004 explains
that boundary. Stub mode is for a local preview, and deterministic CI fixtures test
mechanics without claiming real-model quality.

## Health, scaling and security

Independent liveness reports process health. Readiness checks Redis, catalog, Chroma,
nonempty collection and embedding metadata; dependency failure withdraws endpoints
without restarting a healthy process. The request path rechecks metadata. HPA measures
API CPU, while host-model inference is outside the cluster. More API replicas do not
increase a single host model server's throughput.

Workloads use dedicated ServiceAccounts without mounted API tokens, non-root users,
read-only root filesystems, dropped capabilities and writable temporary mounts.
Default-deny NetworkPolicies permit explicit service paths and DNS. Real inference
adds exact host `/32` egress to TCP 11434. Calico enforcement must be checked on the
minikube deployment; the local k3d fixture operations report is not proof of Calico.

Rolling updates use maxUnavailable 0, maxSurge 1, a 15-second preStop delay and
330-second grace. The saved final fixture run observed no failed requests across
rollout, rollback and Pod deletion; finite samples cannot guarantee all workloads.
JSON request logs and Prometheus metrics provide latency, evidence IDs/scores,
cache outcomes, abstention/fallback and token usage. Raw API keys and question text
are excluded from request logs. See evidence/README.md for measured scope and gaps.
