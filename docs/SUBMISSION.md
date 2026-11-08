# Submission status — 8 November 2026

The application implementation is published on main. PR #7's real acceptance and
namespace fixes are merged into dev. PRs #8–#11 complete evaluation, operational
verification, engineering analysis and audit; integrate their approved green heads
in order, then release dev through a protected PR into main. Their completion does
not mean the newer changes are already released on main.

| Item | Current verified state |
| --- | --- |
| Implementation | API/UI/indexer, pipeline, providers, cache, probes, policies, tests and documentation implemented. |
| CI | Six jobs implemented and exercised on feature PRs/dev: lint, test, manifests, build, scan, e2e-eval. Inspect the latest head's checks before merging. |
| Main protection | Active, main-only target, one approval, six checks and no bypass. Fresh API evidence: evidence/final-protection-verification.json. Expanded UI screenshot remains outstanding. |
| Docker Hub and CD | Configured and verified. Existing main release 6683ba647b317586bb5400d8e3754a71fe8c41a2 passed test/build-push/deploy in run 42494652854; all three SHA tags verified. See evidence/latest-verified-release.json. |
| Gate demonstration | PR #2 is an unmerged draft. Failed/restored evaluation runs and screenshots are retained; never merge it. |
| Fresh real acceptance | Passed run 42498284513: fresh verified nine-source corpus, 950 chunks, frozen fingerprint, genuine supported answer/absent decline, and 27/27 cached requests during ready API Pod replacement. |
| Production indexer memory | Measured cgroup peak 188.43 MiB against unchanged 1 GiB limit; highest kubectl top sample 151 MiB. Parent RSS is separately reported. |
| Revised real-model benchmark | Completed run 42499897552. Recall@5 88.9%, all 8 emitted citations valid, required abstentions 2/2. Six of 18 answerable questions answered, five complete and one incorrect; twelve fallbacks. Baseline unchanged and old output retained. Team review required; no overall quality improvement claimed. |
| Real core operations | Run 42500255265 passed enforced Calico denial with positive controls, PVC recovery, explicit live embedding-pin mismatch and real same-pin reindex continuity (95/95 requests). |
| Real rollout/HPA follow-up | Same run had 337/337 successful rollout/rollback/replacement requests and restored settings, but failed HPA metrics readiness. Corrected run is pending; not yet a complete green operations workflow. |
| Secret scan | Gitleaks found zero findings in the captured history/source snapshots. Repeat after the final evidence updates; never commit credentials, raw source PDFs or kubeconfigs. |
| Unchanged checker | Readable resource mappings, explicit build exclusions and accurate workflow step names reduce historical heuristic failures. Latest recorded audit: 162 passes, 5 warnings, 2 named-stage false positives. See FINAL-SUBMISSION.md and evidence/final-submission-audit.log. Rerun after final integration. |

## Remaining before hand-in

- Finish/review the HPA operational follow-up, then finalize engineering interpretation.
- Hassan reviews feature PRs; merge green changes into dev in order, then approve and
  merge the final dev-to-main PR. The existing cd.yml runs automatically on that merge.
- Confirm test, build-push and deploy all pass for the selected final main SHA; use
  matching image tags and the run link. Older successful releases remain historical.
- The team supplies a truthful personal debugging incident/duration for engineering
  answer 7, reviews the source/ADRs/AI attribution and captures the expanded protection
  screenshot. No first-person experience or unrecorded duration has been invented.
- Submit one team Classroom entry before 23:59 PKT: repository URL with instructor
  access, successful CD URL, three matching Docker Hub SHA-tag links, and committed
  eval/results.json plus eval/baseline.json. See FINAL-SUBMISSION.md.

## Evidence boundaries

The current results use genuine Ollama/Nomic/Llama on a fresh hosted runner, without
the historical CPU embedding adapter or reused answers. Automated citation validity
checks reference membership, not factual correctness: the incorrect conditional
answer remains visible in the semantic review. Finite cached traffic samples are
not an uncached inference throughput guarantee. Chroma PVC recovery briefly removes
the singleton store and is not a claim of storage high availability.

CD uses a disposable deterministic fixture cluster as required for release smoke
checks. It does not publish a persistent real-model service. Main's final release
must be selected after the feature merges; keep source SHA, run and tags consistent.
