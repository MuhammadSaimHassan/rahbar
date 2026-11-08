# Evidence index

Evidence is scoped to the experiment that produced it. Older text logs are retained
as historical records; their original pending-work notes can be superseded by later
measurements. Current acceptance gaps are listed in ../SUBMISSION.md.

| Evidence | What it supports | Limit |
| --- | --- | --- |
| [coding-validation.txt](coding-validation.txt) | Final coding checks: 87 passed, one skip, 82.80% API coverage | Recorded coding run; not a hosted CI/CD result |
| [coding-fixture-results.json](coding-fixture-results.json) | Seven Ingress fixture questions, retrieval and citation/abstention gates | Fictional documents and deterministic generation |
| [operations.json](operations.json) | Three ready addresses, rollout, rollback, Pod replacement, top/HPA output, 135 successful requests, restoration | Finite k3d fixture run; HPA temporarily fixed at three; no indexer peak |
| [operations-before-drain-fix.json](operations-before-drain-fix.json) | One failed request before drain fix | Retained failure, not final acceptance |
| [failure-extraction.json](failure-extraction.json) | OCR on/off real scanned policy | Text coverage, not character accuracy |
| [failure-chunking.json](failure-chunking.json) | Default versus fixed 100/0 evidence mapping | Mapping coverage, not ranked recall |
| [failure-pin.json](failure-pin.json) | Reject incompatible fixture embedding pin; restored search succeeds | Retriever-level check, not a Kubernetes Pod screenshot |
| [failure-source.json](failure-source.json) | Retired fixture hits introduced by removing source filter | Retrieval contamination, not a generated-answer experiment |
| [phase5-retrieval-sweep.json](phase5-retrieval-sweep.json) | Three real-Nomic chunk configurations | Small frozen benchmark |
| [phase5-cache-sweep.json](phase5-cache-sweep.json) | Three thresholds with/without runtime guards | Labeled seeds assumed eligible; limited paraphrase reuse |
| [phase6-local.txt](phase6-local.txt) | Local actionlint, manifests, scans, k3d fixture gate and deliberate failure/restoration | No GitHub merge/protection proof or hosted CD URL |
| [indexer-validation.txt](indexer-validation.txt) | OCR/chunk checks, synthetic publication continuity, parent RSS | Historical milestone; not a production cgroup peak |
| [indexer-preprocessing.json](indexer-preprocessing.json) | Per-source preprocessing and token amplification | Offline preprocessing |
| [corpus-audit.json](corpus-audit.json), [corpus-verification.txt](corpus-verification.txt) | Corpus size, text layers and hash verification | Acquisition audit |
| [table-extraction.txt](table-extraction.txt), [scanned-policy-pdffonts.txt](scanned-policy-pdffonts.txt) | Table example and scanned text-layer inspection | Representative source checks |
| [container-smoke.txt](container-smoke.txt), [kubernetes-stub-validation.txt](kubernetes-stub-validation.txt) | Early image, schema and real-dependency smoke checks | Earlier milestone, not final full-cluster acceptance |
| [golden-preparation.txt](golden-preparation.txt) | Source oracle/projection preparation | No ranked quality measurement |
| [submission-audit.txt](submission-audit.txt), [source snapshot audit](phase8-source-snapshot-audit.txt), [phase8-validation.json](phase8-validation.json) | Current Phase 8 documentation and audit checks | Includes unresolved items; inspect detailed scope |

The historical real-model answers and manual-review facts are in ../../eval/results.json
and ../../eval/baseline.json. They predate the final prompt change.

Hosted evidence: [hosted-release.md](hosted-release.md) records the successful CD run,
the three Docker Hub SHA tags and the PR #2 blocked/green gate, with screenshots
[eval-gate-blocked.png](eval-gate-blocked.png) and [eval-gate-green.png](eval-gate-green.png).
The active main ruleset was independently read through GitHub's API:
[branch-protection-api.json](branch-protection-api.json) records its target, one
approval, all six required check names and empty bypass list. This is configuration
verification, not a UI screenshot; an expanded screenshot remains outstanding.

The second hosted CD run 42476095435 also completed successfully for
622ff386867e35f118b477b8cc645d68d37928fb. See hosted-release.md for matching tags.
PR #2 is an unmerged draft. Current remaining work is listed in ../SUBMISSION.md.


Owner documentation validation on 2026-11-08:
[owner-validation.json](owner-validation.json) records the scope and unchanged checker
summary. Gitleaks v8.30.1 found zero findings in all-ref history (ten commits) and
pending source: [history report](gitleaks-history.json),
[working-tree report](gitleaks-working-tree.json). The official release checksum was
verified before running the scanner. The original checker output is retained in
[owner-submission-audit.txt](owner-submission-audit.txt). These checks do not replace
the pending real-corpus acceptance or expanded browser screenshot.

## Latest real verification and release audit

- real-corpus-acceptance.json, real-corpus-model-tags.json and real-indexer-memory-samples.txt:
  fresh genuine-model acceptance and separately measured cgroup/sample memory.
- real-model-results-20261108.json and real-model-semantic-review.json: revised
  frozen 20-question output, exact run/source provenance and AI-assisted fact review.
  Current eval/results.json is this revised run; old output is under eval/history
  and eval/baseline.json is unchanged. Earlier references to both files as exclusively
  historical are superseded.
- real-runtime-first-core.json: successful Calico/PVC/pin/reindex subtests from an
  overall failed workflow; real-rollout-first-metrics-failure.json retains that
  workflow's HPA failure despite zero sampled traffic failures. Follow-up pending.
- latest-verified-release.json: existing main release 6683ba6, its successful CD
  jobs and three matching Docker tag digests. This predates final feature merges.
- final-protection-verification.json, final-gitleaks-history.json,
  final-gitleaks-working-tree.json and final-submission-audit.log: exact audit scope,
  with two named-Docker-stage checker false positives explicitly explained.

Read ../SUBMISSION.md and ../FINAL-SUBMISSION.md for current remaining human/release
actions. A raw log/artifact is not independent student review or a browser screenshot.
