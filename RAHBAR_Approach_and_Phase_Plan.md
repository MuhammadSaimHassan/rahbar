# RAHBAR — Approach and Phase Plan

A structured plan for completing Assignment 02 (Grounded RAG on Kubernetes) end to end.

---

## 1. What You Are Building

RAHBAR is a grounded question-answering service over a real document corpus (FAST-NUCES public documents), deployed on Kubernetes. It must:

- Answer **only** from the corpus, with citations that match retrieved chunks
- **Abstain** honestly when the corpus does not cover the question
- Re-index **without a redeploy**
- Scale horizontally and survive a deleted pod
- Fail the CI build when retrieval quality drops

### System components

| Component | Kind | Role |
|---|---|---|
| `indexer` | Job + CronJob | The **only writer**. Extract → clean → chunk → embed → store, then exits |
| `api` | Deployment ×3 (HPA 3–8) | **Read-only**. Cache check → embed → retrieve → augment → generate → validate |
| `chroma` | StatefulSet ×1 + PVC | Vector store |
| `redis` | Deployment + PVC | Semantic cache |
| `ui` | Deployment | nginx serving the chat UI (given in starter kit) |
| Supporting | Namespace, Ingress, ConfigMap, Secret, NetworkPolicy, HPA, 4 Services | Config, routing, security, scaling |

### The one idea everything follows from

> Indexing runs once (and again when material changes). Querying runs on every question.

This is why indexing is a **Job**, not API startup, and why the API readiness probe checks that the collection exists and is non-empty.

---

## 2. Overall Approach

### Guiding principles

1. **Cluster first, intelligence second.** Deploy the full system around the starter kit's stub retriever before building the real pipeline. This isolates Kubernetes problems from RAG problems.
2. **One writer, one reader, one pin.** Only the indexer writes to Chroma. The API only reads. Both read the same `EMBED_MODEL` from one ConfigMap, and the code enforces it.
3. **Measure, do not guess.** Chunk sizes, cache threshold and recall are all chosen from numbers you can show.
4. **Write the golden set before tuning.** A golden set derived from what your retriever already returns gives a meaningless number.
5. **Guardrails over rules.** Make bad states unreachable in code (embedding mismatch refuses readiness, citations validated against retrieved chunks) instead of documenting a rule.
6. **Capture evidence as you go.** Screenshots, `kubectl` output and metrics are far harder to reproduce at the end.
7. **Write docs while the reasoning is fresh.** ADRs, pipeline notes and engineering answers should be drafted in the phase where the decision was made.

### Order of attack

```
Setup → Kubernetes (stub) → Corpus → Indexer → Query pipeline → Evaluation → CI/CD → Failure analysis + evidence → Docs + submission
```

---

## 3. Phase Plan

Each phase has **goals**, **tasks**, **exit criteria** (how you know it is done) and **evidence to capture**.

---

### Phase 0 — Setup and Corpus Decision

**Goals:** a working repository, a working local cluster, and an approved corpus choice.

**Tasks**
- [ ] Create the repo from `rahbar-starter.zip` as the first commit; read `STARTER.md`
- [ ] Create `dev` branch; protect `main` (no direct pushes, PR required, CI required, one approval)
- [ ] Set up `.gitignore` early (`*-secret.yaml`, `.env`, corpus PDFs)
- [ ] Start minikube with Calico: `minikube start --driver=docker --cni=calico --memory=6144 --cpus=4`
- [ ] Enable addons: `metrics-server`, `ingress`
- [ ] Install Ollama locally, run with `OLLAMA_HOST=0.0.0.0`, pull `llama3.2:3b` and `nomic-embed-text`
- [ ] Choose the corpus and confirm every document still downloads
- [ ] Name the corpus in the first pull request

**Corpus checklist (all seven properties must be reachable)**
- [ ] ≥ 6 documents, ≥ 40 pages, all public or your own
- [ ] ≥ 2 versions of the same policy (e.g. Academic Rules 2023 vs Handbook 2026)
- [ ] ≥ 1 scanned, image-only PDF (verify with `pdffonts`)
- [ ] ≥ 1 document with a table carrying real information
- [ ] ≥ 1 document with long definitions (Student Handbook)
- [ ] ≥ 1 deliberately absent topic (e.g. hostel rules)
- [ ] Exact-term content (clause numbers, course codes, CGPA thresholds, fees)

**Exit criteria**
- `kubectl get nodes` is Ready; Calico is running; Ollama responds from the host
- Branch protection is on; corpus choice is written down

**Evidence:** branch protection screenshot → `docs/evidence/`

---

### Phase 1 — Kubernetes Around the Stub

**Goals:** the entire system runs on the cluster using the stub retriever, correctly and securely.

**Tasks**

*Images*
- [ ] Dockerfiles for `api`, `indexer`, `ui` with `.dockerignore`
- [ ] Non-root user; load images into minikube; `imagePullPolicy: IfNotPresent`

*Manifests (`k8s/base/` + `k8s/overlays/{dev,prod}/`, all in namespace `rahbar`)*
- [ ] Namespace
- [ ] ConfigMap: chunk size, overlap, `top_k`, relevance floor, cache threshold, temperature (with one-line justification), `EMBED_MODEL`, `LLM_PROVIDER`, `CHROMA_HOST`
- [ ] Secret: placeholder only, committed; real one created by `kubectl create secret` and gitignored
- [ ] `api` Deployment: 3 replicas, three probes, requests and limits, `maxSurge: 1`, `maxUnavailable: 0`, `terminationGracePeriodSeconds`, `preStop` sleep
- [ ] `ui` Deployment
- [ ] `chroma` **StatefulSet** with `volumeClaimTemplates` (reason documented)
- [ ] `redis` Deployment + PVC with persistence
- [ ] 4 ClusterIP Services (Chroma and Redis never NodePort/LoadBalancer)
- [ ] Ingress: `/` → ui, `/api` → api, one host
- [ ] `indexer` Job: `restartPolicy: OnFailure`, `backoffLimit` set
- [ ] `reindex` CronJob (weekly): same image and arguments as the Job
- [ ] HPA on `api`: min 3, max 8, CPU target 70%
- [ ] `kustomization.yaml` for base and both overlays

*Probes*
- [ ] `/healthz`: process alive only. **Must not touch Chroma, Redis or the LLM**
- [ ] `/readyz`: 200 only if Chroma reachable, collection non-empty, Redis reachable; otherwise 503 naming the failed dependency

*Security (five holes, five closures)*
- [ ] Secrets never committed
- [ ] ServiceAccount per workload; `automountServiceAccountToken: false` where not needed
- [ ] `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, all capabilities dropped (mount `emptyDir` for writable paths)
- [ ] NetworkPolicy deny-by-default, then allow: ui ← Ingress; api ← ui + Ingress; chroma ← api + indexer only; redis ← api only; DNS egress to kube-dns (UDP/TCP 53); api egress to Ollama host via `ipBlock`
- [ ] Output treated as untrusted (no `eval`, no SQL built from model output)

*Resources*
- [ ] Requests and limits on **every** container, including the Job
- [ ] Capture `kubectl top pods` and use it to justify numbers

**Exit criteria**
- A question through the Ingress returns the stub's three fixed passages
- Deleting an api pod causes no failure
- ui **cannot** reach chroma (test it)
- HPA shows a real percentage, not `<unknown>`
- `kustomize build k8s/overlays/prod` succeeds

**Evidence:** `kubectl get pods`, `kubectl top pods`, `kubectl get hpa`, `kubectl get endpoints`, NetworkPolicy block test → `docs/evidence/`

**Common traps:** `ImagePullBackOff` (load the image into minikube); DNS stops resolving after default-deny (allow kube-dns); NetworkPolicy ignored (cluster started without Calico).

---

### Phase 2 — Corpus and Indexing Pipeline

**Goals:** a real, correctly indexed vector store with rich metadata, produced by the Job.

**Tasks**

*Corpus acquisition*
- [ ] Fetch script: collect `.pdf` links from index pages, URL-encode filenames, convert Google Drive links, download once with pauses
- [ ] `corpus/MANIFEST.md` with every URL and its SHA-256
- [ ] Commit the manifest and script, **not** the PDFs (unless you own them)
- [ ] Say so in the README

*Pipeline (`indexer/pipeline/{extract,clean,chunk,embed,store}.py`)*
- [ ] **Extract:** PDF → text; detect pages with no text layer and OCR them; strip repeating headers/footers but keep headings and section boundaries; handle tables
- [ ] **Clean:** remove artefacts without destroying structure; note one thing you deliberately did not strip
- [ ] **Chunk:** structure-aware (sections → paragraphs → sentences) with overlap, under a target size
- [ ] **Embed:** one vector per chunk from the pinned model
- [ ] **Store:** id, text, vector, metadata into Chroma

*Metadata (graded)*
- [ ] Every chunk has `source`, `section`, `page`, `doc_version`, `superseded: true|false`

*Embedding pin*
- [ ] Indexer writes model name and vector dimension into the Chroma **collection metadata**

*Cache invalidation hook*
- [ ] Indexer expires the Redis cache when it finishes

*Tests*
- [ ] Unit tests for each stage under `indexer/tests/`

**Exit criteria**
- `kubectl logs job/indexer` shows a clean run and exits 0
- Chroma holds the expected chunk count with the full metadata schema
- Scanned PDF produces searchable text (or the loss is documented honestly)
- Indexer does not OOMKill (exit 137); memory limit justified by `kubectl top`

**Document in `docs/PIPELINE.md`:** which documents needed OCR; one before-and-after table example; what could not be recovered; rules applied; chunk size/overlap; storage amplification (stored tokens ÷ original tokens); model name, vector dimension and where the pin lives; chunk count and metadata schema.

**Document in `docs/CORPUS.md`:** all seven properties, with the specific documents satisfying each.

---

### Phase 3 — Golden Set (before tuning anything)

**Goals:** an honest benchmark written from the documents, not from your retriever's output.

**Tasks**
- [ ] Read the source documents directly and write `eval/golden.yaml` with ≥ 15 questions
- [ ] For each question, list the known relevant chunk ids, or document and section

| Type | Minimum | Tests |
|---|---|---|
| Ordinary, answerable | 8 | Baseline retrieval and grounding |
| Version-sensitive | 2 | `doc_version` filter |
| Exact term | 2 | What embeddings blur |
| Must abstain | 2 | Honest refusal |
| Prompt injection | 1 | Retrieved and user text treated as data |

- [ ] Also build a small cache-test question set: paraphrases that **should** hit, and near-miss questions that **must not** (for threshold tuning)

**Exit criteria:** golden set committed before any tuning run.

---

### Phase 4 — Query Pipeline

**Goals:** the real retrieval and generation path replaces the stub, with every safety property in place.

**Tasks**

*Flow (`api/app/{routes,services,retrieval,providers}/`)*
- [ ] Validate input (3–500 characters)
- [ ] Cache check (skip for follow-ups)
- [ ] Embed with the pinned model
- [ ] Retrieve top-k with `k` from ConfigMap and a metadata filter excluding `superseded` documents (unless the user explicitly asks about an older version)
- [ ] Augment: instructions → numbered, **delimited** evidence → question
- [ ] Generate at low temperature (0–0.3) with schema enforcement
- [ ] Validate with Pydantic; retry once; then return a safe canned response (never a 500)
- [ ] Store the turn; write a cache entry only if safe

*Answer contract*
- [ ] `Answer`: `reasoning` (stripped before display), `answer`, `citations`, `answered_from_context`, `confidence`

*Grounding and honesty*
- [ ] Relevance floor: if nothing clears it → `answered_from_context: false` and a clear "the corpus does not cover this"
- [ ] Every citation must match a chunk actually retrieved for that request
- [ ] Prompt-injection defence: delimit retrieved text, constrain to schema; write one test that indexes a **poisoned chunk** and asserts it is not obeyed

*Provider interface*
- [ ] `LLM_PROVIDER` selects the provider (`base`, `ollama`, `hosted`, `stub`); swapping is one file
- [ ] Implement `ollama-host` fully; `hosted` optional

*Semantic cache*
- [ ] Cosine-similarity threshold from ConfigMap
- [ ] **Never** cache follow-ups, abstentions, out-of-scope answers, or failed validations
- [ ] Invalidated on re-index
- [ ] Choose threshold with data: the lowest threshold with zero false hits; record two or three thresholds tried and the false hit that ruled one out

*Embedding-pin guardrail*
- [ ] At startup, compare the collection metadata with the API's `EMBED_MODEL`; on mismatch, refuse readiness and log exactly what conflicts

*Observability*
- [ ] JSON logs to stdout, with `request_id` from `X-Request-ID` or generated
- [ ] `/metrics` (Prometheus format): request count and latency, retrieval latency, generation latency, cache hit ratio, abstention count, fallback count, tokens in/out
- [ ] One log line per request: `top_k`, retrieved chunk ids, similarity scores, abstention flag

*Tests*
- [ ] `pytest` with stub provider, no network, coverage ≥ 60% on the app package

**Exit criteria**
- Real answers with valid citations through the Ingress
- Absent-topic question is declined
- Changing `EMBED_MODEL` and restarting the API leaves the pod at `0/1 READY` with a log line naming the conflict
- Re-index via `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar` works with no redeploy and no downtime, and the cache is cleared

**Evidence:** guardrail demonstration (pod at `0/1 READY` plus log line) → `docs/evidence/`

---

### Phase 5 — Evaluation and Tuning

**Goals:** numbers that justify every design choice, plus a committed baseline.

**Tasks**
- [ ] Build `eval/run_eval.py`: runs against a live stack, writes `eval/results.json`
- [ ] Report **recall@3 and recall@5**, overall and by question type
- [ ] Report **citation validity** (% of citations matching retrieved chunks)
- [ ] Report **abstention correctness** (must be 100%)
- [ ] Run **at least three** (size, overlap) chunking configurations, measure recall@5 for each, put them in a table in `PIPELINE.md`, and justify the shipped one
- [ ] Tune the cache threshold (Phase 4 data)
- [ ] Note that exact-term recall is worse than definitional recall, and explain why
- [ ] Commit `eval/baseline.json` with your shipped numbers

**CI gate rules (what `run_eval.py` must enforce)**

| Fails if… | Threshold |
|---|---|
| recall@5 drops below baseline | more than 5 percentage points |
| A must-abstain question answered from context | any |
| Citation validity | below 95% |

**Exit criteria:** `results.json` and `baseline.json` committed; chunking table written; cache threshold justified.

---

### Phase 6 — CI/CD Pipelines

**Goals:** every change goes from pull request to cluster through gated workflows.

**`ci.yml` — on PR to `main` and push to `dev`**

| Job | Task |
|---|---|
| `lint` | `ruff`, `mypy` (and `eslint`/`tsc` if the UI has a build step) |
| `test` | `pytest` with coverage ≥ 60%, stub provider |
| `manifests` | `kustomize build k8s/overlays/prod \| kubeconform -strict` |
| `build` | Build api, ui, indexer images; **do not push** on PRs |
| `scan` | Trivy, failing on HIGH/CRITICAL with a fix available |
| `e2e-eval` | kind or k3d cluster → apply manifests → run indexer Job on the **fixture corpus** → wait for rollout → run `eval/run_eval.py` → enforce the gate |

**`cd.yml` — on push to `main`**
- [ ] `test` → `build-push` (`needs: test`, push to Docker Hub tagged `${{ github.sha }}`) → `deploy` (`needs: build-push`: ephemeral cluster, `kubectl rollout status`, smoke test via Ingress)

**Non-negotiables**
- [ ] `needs:` on every publishing/deploying job
- [ ] Deploy by commit SHA, **never `:latest`**
- [ ] Docker Hub **access token** in GitHub Secrets (never your password)
- [ ] Least-privilege `permissions:` block in every workflow

**Demonstrate the gate**
- [ ] Open a PR that deliberately fails the eval gate → screenshot the greyed-out merge button
- [ ] Fix it → screenshot green

**Exit criteria:** a successful `cd.yml` run (tested, published, deployed); images on Docker Hub with SHA tags.

**Evidence:** blocked-merge and green-merge screenshots, link to the successful `cd.yml` run → `docs/evidence/`

---

### Phase 7 — Operational Demonstrations and Failure Analysis

**Goals:** prove the system behaves as designed, and show you understand how it breaks.

**Operational demonstrations**
- [ ] `kubectl set image` → `kubectl rollout status` → `kubectl rollout undo` (previous version serving again)
- [ ] Scale to ≥ 3 → `kubectl get endpoints` lists that many IPs
- [ ] Delete a pod → no user-visible breakage
- [ ] `kubectl top pods` output committed to justify requests/limits

**Break four of the six stages, one at a time** (`docs/FAILURE-ANALYSIS.md`)

| Stage | How to break it |
|---|---|
| A · Extraction | Index the scanned PDF without OCR |
| B · Chunking | Fixed-size 100-token chunks, no overlap |
| C · Retrieval | `top_k: 1`, or change `EMBED_MODEL` on the API only |
| D · Prompt | Remove the "use the supplied context" instruction |
| E · Source | Remove the superseded filter, ask a version-sensitive question |
| F · Generation | Temperature 1.2 |

For each, record: **symptom → diagnosis → stage → remedy**, plus how you would have diagnosed it *without* causing it, and which metric or log field would have shown it. (Only F is the model's fault: check A–E first.)

**Exit criteria:** four failure write-ups with before/after numbers; all demonstrations captured.

---

### Phase 8 — Documentation and Submission

**Goals:** a repository a stranger can run from a clean clone, with honest documentation.

**Documents**
- [ ] `docs/adr/0001-indexer-as-job.md` — in your own words (the first file the marker reads)
- [ ] `docs/adr/0002…0004` — including the cache store choice (Redis vs second Chroma collection) and LLM provider and data governance
- [ ] `docs/ARCHITECTURE.md` — including why Chroma is a StatefulSet
- [ ] `docs/CORPUS.md`, `docs/PIPELINE.md`, `docs/FAILURE-ANALYSIS.md`
- [ ] `docs/AI-USAGE.md` — name the tools, what they wrote or shaped, and what you changed and why
- [ ] `docs/ENGINEERING-NOTES.md` — answers to the seven questions below, referencing real files and line numbers
- [ ] `README.md` — apply order that works from a clean clone, `kubectl create secret` line, corpus fetch explanation, embedding-through-Ollama note

**The seven engineering questions**
1. What breaks if indexing moves into API startup (failure, preventing object, manifest line)?
2. What happens if readiness and liveness are swapped and Chroma is slow for 90 seconds?
3. What does the CPU-based HPA measure while the model generates, and which signal should scale it?
4. Indexer peak memory, your limit, your margin, and the exit code if wrong (137)?
5. Where is recall@5 worst by question type, why, and which RAG technique addresses it (hybrid retrieval)?
6. What happens when `EMBED_MODEL` changes and only the API restarts, with and without the guardrail?
7. The failure that cost you more than an hour: symptoms, what you wrongly believed, the command or log line that told the truth

**Pre-submission checks**
- [ ] `python scripts/check_submission.py` runs clean
- [ ] Clean-clone test: clone fresh, follow the README apply order, get an answer through the Ingress
- [ ] Search Git history for secrets (rotate and write a two-line incident note if any are found)
- [ ] All requests/limits present; HPA not `<unknown>`; nothing in the `default` namespace
- [ ] No direct commits to `main`

---

## 4. Final Deliverable

### Submit on Google Classroom

1. GitHub repository URL (public, or private with both instructors added)
2. Link to a successful `cd.yml` run that tested, published and deployed
3. Link to your Docker Hub images showing SHA tags
4. `eval/results.json` and `eval/baseline.json`, committed in the repository

### Repository contents

```
rahbar/
├── api/            # FastAPI service (reads the index, never writes it)
├── indexer/        # Job image (the only writer)
├── ui/             # nginx chat UI
├── corpus/         # MANIFEST.md + fetch script
├── eval/           # golden.yaml, run_eval.py, baseline.json, results.json, fixtures/
├── k8s/            # base/ + overlays/{dev,prod}/
├── docs/           # CORPUS, PIPELINE, FAILURE-ANALYSIS, ENGINEERING-NOTES, AI-USAGE,
│                   # ARCHITECTURE, adr/0001–0004, evidence/
├── scripts/        # check_submission.py
├── .github/workflows/{ci.yml,cd.yml}
└── .gitignore · Makefile · README.md · LICENSE
```

### The acceptance test ("done" means this works)

A stranger clones the repo, starts minikube, applies your manifests in the documented order, runs the indexing Job, and asks a question through the Ingress.
1. They get a **cited, grounded** answer.
2. They ask about the **absent topic** and the service **declines**.
3. They **delete a pod** and nothing breaks.

---

## 5. Automatic Deductions to Avoid

| Violation | Deduction |
|---|---|
| Any secret/key/password in Git history | −20 |
| Base64 Secret with a real value in a committed manifest | −15 |
| Indexing at API startup instead of in a Job | −10 |
| A returned citation not matching a retrieved chunk | −10 |
| A must-abstain question answered from context | −10 |
| Chroma/Redis as a Deployment with no PVC, or exposed as NodePort/LoadBalancer | −8 |
| Embedding model not pinned, or indexer and API can disagree silently | −8 |
| Container with no requests, or HPA reading `<unknown>` | −6 |
| Publishing/deploying job without `needs:`, or deploying `:latest` | −6 |
| Manifests in the `default` namespace | −5 |
| README apply order that fails from a clean clone | −5 |
| Commits pushed directly to `main` | −4 |

---

## 6. Debugging Order (use every time)

1. `kubectl get pods` — status
2. `kubectl describe pod <name>` — read **Events** at the bottom
3. `kubectl logs <name>` (add `--previous` for a crashed container) — application output

### Quick symptom reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImagePullBackOff` on local image | minikube can't see host Docker images | `minikube image load <image>:<tag>`; `imagePullPolicy: IfNotPresent` |
| Service names stop resolving | Default-deny egress blocks DNS | Allow egress to kube-dns on 53 (UDP and TCP) |
| api can't reach Ollama | Ollama on 127.0.0.1, or policy blocks host | `OLLAMA_HOST=0.0.0.0`; `ipBlock` egress for the host IP |
| ui can reach chroma | Cluster started without Calico | Recreate with `--cni=calico` |
| HPA `<unknown>/70%` | No `requests.cpu` or metrics-server off | Add requests; enable the addon; wait about a minute |
| Indexer exit code 137 | OOMKilled | Raise memory limit, guided by `kubectl top pods` |
| api Running but `0/1 READY` | Readiness failing (empty collection, bad path, or pin guardrail) | `describe pod`, then `logs` |

---

## 7. Scope Notes

- **Do:** `ollama-host` mode as the default provider
- **Skip:** `ollama-incluster` (bonus, needs 8 GB and a long startup probe)
- **Do first:** Kubernetes around the stub before any real RAG code
- **Do early:** corpus approval, golden set, `.gitignore`, and evidence capture


## Implementation status update — 2026-11-07

The original checklist above is retained as the planning baseline. Phase 8's required
written documents are now populated and aligned with the code and saved measurements.
See `docs/SUBMISSION.md` for the current deliverable-by-deliverable status and
`docs/evidence/README.md` for the evidence map. Hosted release, clean-clone acceptance,
production indexer peak memory, remaining deployment proofs and team review are not
marked complete by this documentation update.
