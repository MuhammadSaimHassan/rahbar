# Submission status — 2026-11-08

The complete implementation is on protected main via PR #1. PR #3 added hosted
release and evaluation-gate evidence. Both recorded hosted CD runs passed, including
the deployment job. Written documentation and hosted release evidence are substantially
complete; the runtime checks and personal review below remain outstanding.

## Completed implementation, documentation and hosted delivery

| Item | Verified status |
| --- | --- |
| Published source | Done: PR #1 merged the complete implementation; PR #3 merged release/gate evidence. The old statement that the shared implementation is uncommitted is superseded. |
| Branches and protection | Done: main is protected by active Protect main ruleset, with one approval, all six CI checks, and no bypass actors. See evidence/branch-protection-api.json. Expanded browser screenshot is still pending. |
| Docker Hub / Actions configuration | Done: existing configured namespace/secrets produced successful image publication. No secret values are recorded in documentation. |
| First hosted release | Done: run 42474907543 passed test, build-push and deploy for 3a53930b91aa7db24e40ab8ef25a72684f293b87. |
| Second hosted release | Done: run 42476095435 passed all three jobs for 622ff386867e35f118b477b8cc645d68d37928fb. |
| Three SHA-tagged images | Done: API, UI and indexer tags were verified for both releases; links are in evidence/hosted-release.md. |
| Failed and restored eval gate | Done: PR #2 and committed screenshots show a deliberate gate failure and restored green checks. |
| Demo safety | Done: PR #2 is an open draft and remains unmerged. Its historical failure/restore links are retained. |
| Written documents | README, ARCHITECTURE, CORPUS, PIPELINE, FAILURE-ANALYSIS, ENGINEERING-NOTES, AI-USAGE, ADRs 0001–0004 and operational runbooks are populated. Team review remains required. |

## Remaining acceptance work

| Item | Required action and current limitation |
| --- | --- |
| Expanded branch-protection screenshot | Capture active enforcement/main target, the one-approval setting and all six checks with their additional settings expanded. Browser automation failed to initialize during this update. The saved API JSON verifies the configuration but does not replace the requested UI screenshot. |
| Clean-clone real acceptance | On a suitable machine, clone merged main into a fresh directory, rebuild/fetch/index, obtain a grounded cited answer and correct absent-topic decline through Ingress, and delete an API Pod under traffic. Not established by the hosted fictional fixture. |
| Revised real-model benchmark | Rerun the frozen 20 questions after the prompt revision. Preserve historical results/baseline and manually review answer facts, omissions, fallbacks and citations. No improved live-model quality is claimed. |
| Production operational evidence | Capture Calico UI-to-Chroma denial with a positive control, PVC persistence, live pin-mismatch readiness/logs, and real same-model re-index/cache continuity. Existing fixture operations are separately scoped. |
| Production indexer memory | Measure the whole-container/cgroup peak with samples during production indexing. The earlier 159 MiB parent-process RSS is not the Job's final memory peak or safety margin. |
| Engineering answer 7 | Supply a truthful personal/team debugging account and duration. The 502 drain incident and checksum/download incidents may be documented only with accurate attribution. No student's first-person experience has been invented. |
| Team documentation review | Review ADRs, source references and AI attribution. Read PARTNER_HANDOFF.md alongside this current status, because its earlier GitHub-pending notes are now historical. |
| Final audit | Gitleaks v8.30.1 found zero findings in all-ref history (ten commits) and pending files on 2026-11-08. The unchanged checker was rerun; see evidence/owner-validation.json and owner-submission-audit.txt. Review its remaining heuristic findings and repeat checks after further edits. |
| Classroom submission | Confirm instructor access and submit repository, successful CD run, matching three image-tag links and committed eval/results.json and eval/baseline.json by 2026-11-08 23:59 PKT. |

The current local environment does not meet the documented 6 GiB cluster plus host
inference budget. A suitable machine is required before the outstanding real-model
acceptance can be honestly marked complete. Hosted CI/CD uses deterministic fictional
fixtures and does not establish real-model accuracy.

## Release links for hand-in

- Repository: https://github.com/MuhammadSaimHassan/rahbar
- Latest verified recorded CD: https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42476095435
- Matching SHA: 622ff386867e35f118b477b8cc645d68d37928fb
- Image links and earlier release: evidence/hosted-release.md
- Committed historical real results: eval/results.json and eval/baseline.json (initial baseline commit 2e5512d); revised-prompt run pending.

Any later main merge starts another CD run. Inspect that run and use matching run/SHA
links for the release selected for submission. Keep earlier runs labeled as historical.

## Historical checker interpretation

The Phase 8 working-tree audit recorded 145 passes, ten warnings and 13 failures;
a clean nonignored-source snapshot recorded 144 passes, six warnings and the same
13 failures. These were dated observations, not a fresh audit of current main.

| Historical finding | Source-backed explanation |
| --- | --- |
| Requests/limits missing (2) | Parsed compact YAML confirms CPU/memory requests and limits on all six base container definitions. |
| Unpinned runtime bases (2) | FROM runtime refers to the previously pinned Python build stage, not an external unpinned image. |
| Docker exclusions missing (4) | Allowlist contexts begin with * and explicitly exclude nested Python caches; the checker does not model allowlist semantics. |
| CI commands missing (5) | Workflows call strict shell wrappers that actually execute pytest, lint, Trivy, rollout and evaluation. |

Readiness checks collection count, answer.py excludes unsafe cache cases, and all six
base containers drop ALL capabilities. The checker also counts six stage names in
prose although only four measured failure experiments are claimed. Do not add fake
commands or edit/disable the checker merely to manufacture a pass.

Old warnings claiming no dev branch or only one author must not be copied as current
facts: the repository now has dev and contributions from both members. The assignment
specifies no mandatory 60% commit ceiling; the starter checker warns when either of
the top two authors has below 35% of non-merge commits. Record genuine work under the
correct identity and retain AI disclosure.


Latest documentation audit: 147 passed · 9 warnings · 13 failures. This is an unchanged-checker observation, not a real deployment acceptance result.

## Real acceptance update � PR #7, 2026-11-08

PR #6 synchronized main into dev. PR #7 adds hosted real acceptance and corrects
the real overlays' missing namespace. Run 42498284513 passed with fresh verified
corpus, genuine cited/absent-topic Ingress responses and cached request continuity
during Pod replacement (27/27). Production indexer whole-container peak is now
measured: 188.43 MiB under the unchanged 1 GiB limit. See
REAL-CORPUS-ACCEPTANCE.md and evidence/real-corpus-acceptance.json. These supersede
the earlier pending entries for clean real acceptance and indexer peak; merge/review
and final release are still required. Full revised benchmark and the separately
listed operational experiments remain outstanding.
