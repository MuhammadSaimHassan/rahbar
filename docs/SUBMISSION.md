# Submission status — 2026-11-07

The Phase 8 documentation has been completed against the current working tree.
The assignment is not yet submission-ready. This checklist separates written
explanations from acceptance evidence that still requires a run or account setup.

## Completed documentation

- README: preview, fresh real deployment apply order, corpus fetching, Ollama, Secret creation, endpoints and verification.
- ARCHITECTURE: state ownership, Chroma StatefulSet/PVC, Redis, request/publication flow, scaling and security.
- ADRs 0001–0004: independent Job, immutable publication, Redis versus a second Chroma cache collection, provider/data governance.
- CORPUS and MANIFEST: public sources, hashes, versions, scans/tables and absent topic.
- PIPELINE: OCR/cleaning/chunking, metadata/pin, token amplification, three measured chunk settings, cache sweep and honest model-quality review.
- FAILURE-ANALYSIS: four independently measured changes with symptoms, diagnostics, remedies and measurement limits.
- ENGINEERING-NOTES: seven code-specific answers with line references; missing memory/duration evidence identified explicitly.
- AI-USAGE: substantial Codex authorship and subsequent corrections disclosed.
- CI-CD, KUBERNETES and OPERATIONS: setup and operational runbooks; evidence/README links the saved observations.

## Acceptance work remaining

| Item | Status and required action |
| --- | --- |
| Publish completed working tree | Many implementation/document files are currently uncommitted or untracked. Review and commit on a working branch, then publish through the agreed GitHub workflow. A clone of the current remote cannot be assumed to contain these files. |
| GitHub protection and collaboration | Configure dev/main workflow, required PR checks and one approval; capture protection evidence. Existing local history is short and has one author; do not fabricate historical contributions or rewrite it to appear otherwise. |
| Docker Hub and hosted CD | Configure DOCKERHUB_NAMESPACE variable plus DOCKERHUB_USERNAME and DOCKERHUB_TOKEN secrets. **Done:** CD run 42474907543 passed and all three images carry the SHA tag; see evidence/hosted-release.md. |
| Blocked/green merge proof | **Done:** PR #2 (demo only, never merged) shows the blocked gate and the green restore; screenshots and run URLs are in evidence/hosted-release.md. |
| Clean-clone acceptance | After publication, clone into a new directory and follow README without reused raw files, images or volumes. Obtain a grounded cited answer and a correct absent-topic decline through Ingress. Repeat Pod deletion under traffic. This revised working tree has not passed that exact fresh-clone procedure. |
| Revised real-model benchmark | Rerun the frozen 20 questions after the prompt change. Preserve historical baseline/results for comparison; manually review answer facts as well as citation validity. The historical run had 11 fallbacks among 18 answerable questions and one incorrect grounded answer. |
| Production operational evidence | Capture Calico UI-to-Chroma denial, PVC persistence, live embedding-pin mismatch and real-model re-index continuity on the documented deployment. Fixture operation evidence does not prove all of these. |
| Indexer memory answer | Record production whole-container/cgroup peak and samples while OCR/indexing runs. The 159 MiB parent RSS measurement does not establish the real Job's safety margin. |
| Team review | Review the ADRs and AI-authored explanations; supply a truthful personal incident account/duration for engineering question 7. No student rewrite or hour-long debugging history is invented. |
| Submission audit | Inspect evidence/submission-audit.txt and evidence/phase8-validation.json. The original checker remains unchanged; heuristic failures must be evaluated alongside source and outstanding acceptance checks. Rerun after final changes. |
| Final Git review | The Phase 8 audit checks local history and the source snapshot for common credential formats. Repeat a dedicated secret scan before pushing; pattern checks cannot prove the absence of all secrets. |

An optional live hosted-generator test needs credentials and a compatible strict-schema
model only if that provider is selected. Ollama is the primary assignment provider.

## Classroom hand-in

| Required deliverable | Current value |
| --- | --- |
| Repository | https://github.com/MuhammadSaimHassan/rahbar — publish completed files and verify instructor access |
| Successful cd.yml run URL | https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42474907543 |
| Docker Hub API/UI/indexer links with SHA tags | Tag links for SHA 3a53930b91aa7db24e40ab8ef25a72684f293b87 are listed in evidence/hosted-release.md |
| Committed eval/results.json and eval/baseline.json | Historical Phase 5 files exist and were committed in 2e5512d; revised prompt run pending |

The assignment states a deadline of 2026-11-08 at 23:59 PKT. Submit the actual links;
this status document is not a substitute for successful runs or instructor access.

## Interpretation of the Phase 8 checker output

The original checker was run unchanged. The working checkout reports 145 passes,
10 warnings and 13 failures; its source traversal also warns about an inaccessible
Windows/WSL filesystem entry. An isolated nonignored-source snapshot, audited from
its own root, reports 144 passes, six warnings and the same 13 failures. That snapshot
has no Git metadata and therefore skips history checks. It is a static source audit,
not a clean-clone deployment test.

| Reported failures | Source verification |
| --- | --- |
| Missing requests and limits (2) | YAML parsing confirms CPU/memory requests and limits on all six base workload container definitions, including Job and CronJob. See phase8-validation.json and k8s/base/*.yaml. |
| Unpinned runtime bases (2) | indexer/Dockerfile declares `FROM python:3.12.16-slim-bookworm AS runtime`; the other FROM instructions reference that local stage. |
| Missing .git and __pycache__ exclusions (4) | Both Docker ignore files start with `*`, allow only runtime code/requirements, and exclude nested Python caches. The checker does not interpret allowlist semantics. |
| Missing pytest, linter, Trivy, rollout and evaluator steps (5) | Workflows call scripts/ci-checks.sh, scripts/ci-scan.sh and scripts/ci-cluster.sh, which execute these commands and propagate failures with strict shell settings. The checker searches workflow text without following wrappers. |

Additional warnings about readiness, cache exclusions and capabilities are also
heuristic: health.py checks collection count; answer.py bypasses unsafe cache cases;
YAML parsing confirms `drop: [ALL]` on all six base containers. Git workflow warnings
(short history, one author, no dev branch) are genuine remaining process issues.
The lint also counts six failure-stage names because prose mentions prompt and
temperature; only four measured stage experiments are claimed. No checker output
should be treated as a substitute for the required acceptance demonstrations.
