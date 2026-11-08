# Final release and submission

The actual release workflow is `.github/workflows/cd.yml` (the assignment also
calls it cd.yml). It is implemented and has already successfully tested, published
and deployed main. No new credentials or local Docker installation are needed for
the hosted run.

## Review and integration order

1. PR #7: fresh real corpus acceptance and namespace correction.
2. PR #8: frozen 20-question real-model evaluation and reviewed results.
3. PR #9: real network/persistence/pin/reindex/rollout observations.
4. PR #10: engineering measurements and final interpretation.
5. Final audit PR: readable unchanged resource values, clear CI/CD step names,
   explicit build exclusions, current reports and delivery instructions.

These branches are stacked. Merge a prerequisite before its dependents, bring the
new dev into the next branch when its tested contents change, and let all six CI
checks pass. Obtain Hassan's review before merging. PR #2 is the deliberate gate
demonstration: keep it a draft and never merge it.

Then create a pull request from dev to main. Main protection requires the checks
lint, test, manifests, build, scan and e2e-eval, plus one approval. Merge normally,
without bypassing protection or pushing main directly.

## Complete CD

The merge automatically starts CD. Verify test, build-push and deploy all finish
successfully. Build-push publishes API/UI/indexer images tagged with that exact
main merge SHA; deploy pulls those tags, creates a fresh k3d fixture cluster,
waits for indexing and rollout, and tests through Ingress. This deployment verifies
release mechanics with deterministic fixtures; the separate real runs measure the
actual public corpus and Ollama outputs.

Use the Actions run's source SHA to select all three tags. A successful older run
is valid historical evidence but does not prove that newer features were released.
Do not mix a run URL from one revision with image links from another.

## Google Classroom: one entry per team before 23:59 PKT on 8 November

The assignment requires these four items:

1. Repository: https://github.com/MuhammadSaimHassan/rahbar (public, or private with both instructors added).
2. A successful CD run URL showing test, build-push and deploy.
3. Three Docker Hub image links with matching full-SHA tags: saimhassan005/rahbar-api,
   saimhassan005/rahbar-ui and saimhassan005/rahbar-indexer.
4. eval/results.json and eval/baseline.json committed in the repository, with
   the measured results, historical context and semantic limitations explained.

Latest verified existing release (before final feature merges):
https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42494652854
SHA: 6683ba647b317586bb5400d8e3754a71fe8c41a2. Matching tags were verified for all
three repositories. Replace these with the final release's matching values after
its CD succeeds.

Team review remains necessary: understand the code/ADRs and AI disclosure, provide
a truthful personal debugging account where required, and capture the expanded
main-protection settings screenshot. The ruleset API evidence verifies the saved
settings but is not a browser screenshot. Credentials must remain out of evidence.

## Unchanged checker interpretation

Run python scripts/check_submission.py from the final source root. The current
snapshot reports 162 passes, 5 warnings and 2 failures. Both failures treat FROM
runtime as an external unpinned base; in indexer/Dockerfile, runtime is a named
stage derived from python:3.12.16-slim-bookworm. It is valid multistage inheritance.
The checker was not changed or disabled. The image build/scan and real Job provide
additional validation. Later source updates require a newly dated audit result.

The remaining warnings include placeholder-only Secret history, a heuristic commit
count, and checks delegated to helpers: readiness performs a real nonempty count;
answer caching excludes follow-ups, abstentions and invalid responses. Inspect the
actual code and tests. Do not fabricate commits, experiences, outputs or commands to
make a heuristic appear green. The team must complete the final Classroom upload.
