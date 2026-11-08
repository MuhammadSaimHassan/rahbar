# Fresh real-corpus acceptance on a hosted runner

This is separate from the deterministic fixture CI. The public repository's standard
ubuntu-24.04 runner provides four CPUs and 16 GB RAM, so a developer's smaller Windows
machine does not have to run the cluster or inference. No larger paid runner or model
API key is requested. See the [official runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Trigger and review

The real-corpus-acceptance workflow listens to relevant PRs into dev. A maintainer
adds the `run-real-corpus` label to opt into the heavy run. Keep it present while
fixing a failed run; remove it after collecting a passing run to avoid repeating
model downloads for evidence-only changes. Normal six-job CI always remains separate.
Manual workflow_dispatch is also available once the workflow exists on the default
branch. The job has read-only repository permissions and only accepts same-repository
PRs or a manual dispatch.

## What actually runs

- A fresh checkout; pinned public corpus downloaded and SHA-256 verified, without cached PDFs/models/volumes.
- Minikube v1.39.0 verified against its official checksum, Kubernetes v1.35.5, Docker driver, Calico, ingress and metrics-server.
- A 6 GiB/four-CPU cluster and a separate host Docker Ollama 0.6.5 instance.
- Real nomic-embed-text and llama3.2:3b, with a 4,096-token context, one inference request at a time, and capacity for both models to stay loaded. Actual model tags/IDs are recorded.
- Source-built API/UI/indexer images and the real-query overlay, with both inference-host /32 egress policies configured.
- Genuine extraction/OCR/chunking/embedding/publication. A shell wrapper prints the production report and final cgroup memory.peak before the writer exits; the parent RSS is retained separately.
- Ingress UI, a supported CGPA answer with current-source citations and the frozen 400/50 fingerprint, a real absent-topic decline, and requests during replacement of a ready API Pod.
- Cleanup of only this run's uniquely named cluster and inference container.

The application timeouts and relevance/cache settings are not silently relaxed to make
acceptance pass. A failure retains diagnostics. The supported-answer fact check is a
small smoke check, not a substitute for manual semantic review or the 20-question run.

## Artifacts and limits

Download the `real-corpus-acceptance` artifact (seven-day retention). Inspect:

- real-acceptance.json: passed flag, full public-question responses, provenance headers, endpoint addresses and traffic samples.
- indexer.log: production statistics and whole-container cgroup peak.
- indexer-memory-samples.txt: timestamped metrics-server samples, including startup gaps.
- model-tags.json, ollama-version.json and environment.txt: reproducibility context.
- deployment.yaml and cluster/API/model logs: actual configuration and diagnostics.

Do not upload raw PDFs, model blobs, kubeconfigs or Secret values. The artifact is a
record of a finite CPU run. It does not by itself prove all policies, PVC replacement,
rollout/rollback, real re-index continuity or full golden-set accuracy. Those remain
separate tasks. Only mark this acceptance done after a passing actual run, and cite
the run/source commit when committing the reviewed summary. Retain failures honestly.

Run the client directly only against an explicitly named ephemeral rahbar-real-*
context; the orchestration shell refuses non-GitHub-hosted environments to protect
unrelated local projects.


## First hosted run and correction

Run 42496893362 verified downloads and started the real cluster but failed before
indexing: the outer real overlays had omitted namespace: rahbar, creating their added
inference policies in default. Both overlays now set the namespace, CI validates both
real renders, and a regression checks every rendered namespaced resource. The failed
run is retained in evidence/real-corpus-first-failure.json; it is not a passing run.
The runner also detects Failed/FailureTarget Job conditions promptly, rather than
waiting for a completion condition that a failed Job cannot reach.

The next run (42498011937) stopped during the host Ollama startup probe with a
connection reset (curl 56), before cluster deployment. The probe now retries all
transient startup errors within a bounded two-minute window. This is not a change
to application inference timeouts or acceptance criteria.

## Reviewed passing run — 2026-11-08

[Run 42498284513](https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42498284513)
passed on source head 9339fbd, tested merge checkout bee627163f591e438e8f9270abe279f5f0efae95.
All six normal CI jobs also passed for that source. The committed result is
[evidence/real-corpus-acceptance.json](evidence/real-corpus-acceptance.json).

Fresh verified downloads reproduced all nine documents, 950 chunks and the frozen
400/50 fingerprint. Ingress returned the genuine Ollama CGPA answer (2.00, current
policy physical page 24) and correctly declined the absent shuttle timetable. Three
ready Service endpoints were checked; replacement of a ready API Pod completed with
27 successful sampled requests and zero sampled failures. Every replacement sample
was a cache HIT after warming: this proves finite cached request continuity, not
uncached inference capacity or a load-test SLA.

The production Job completed under its unchanged 1 GiB limit. Its final cgroup peak
was 197,578,752 bytes (188.43 MiB), separately from parent RSS 195,276,800 bytes. This
is 18.40% of the limit with 835.57 MiB observed headroom in this one run, not a bound
on larger corpora. Timestamped metrics-server samples and actual model digests are
committed alongside the result. Raw diagnostic artifacts expire after seven days.

Full 20-question evaluation, enforced denial/PVC/pin/re-index/rollout experiments,
team review and final release audit remain separate. This branch targets dev; the
result does not claim these changes are already released on main.
