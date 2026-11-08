# RAHBAR CI/CD

## Checks and deployment

CI runs on pull requests to `main` or `dev`, and pushes to `dev`. It checks Python
lint and types, enforces 60% API coverage, validates the production and CI
manifests with kubeconform, and builds all three application images. The
images are passed to the Trivy and fixture jobs as a short-lived artifact.
Trivy fails on fixable HIGH or CRITICAL findings.

The fixture job creates an isolated k3d cluster and applies the CI overlay.
The real indexer reads three fictional Markdown files and publishes to
Chroma and Redis. The real API retrieves from that index and calls a
deterministic Ollama substitute. Requests enter through Traefik. The gate
uses the fixture-specific baseline, then checks factual responses, historical
edition filtering, and the planted instruction in a retrieved chunk. These
checks cover deployment and pipeline behavior with deterministic fixtures.
The real-model quality measurements are in the Phase 5 results.

CD runs on pushes to `main`. The publish job waits for tests, builds and
scans the images, then pushes the full commit-SHA tags to Docker Hub. The
deploy job waits for publishing, pulls those tags and imports them into a
fresh k3d cluster. It waits for indexing and rollout, then checks the UI
and API through Ingress. That deployment uses the fictional fixture overlay.

## GitHub and Docker Hub setup

1. Set the GitHub repository variable `DOCKERHUB_NAMESPACE` to the namespace
   that owns the three Docker Hub repositories `rahbar-api`, `rahbar-ui`,
   and `rahbar-indexer`.
2. Add `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` as GitHub Actions secrets.
   The token must be able to push the images. Configure it in GitHub rather
   than entering it in the project files or a chat message.
3. Once the repository has a `main` branch and the first CI checks are
   visible, protect `main`. Require a pull request, one approval, and the
   CI jobs `lint`, `test`, `manifests`, `build`, `scan`, and
   `e2e-eval`. Keep `dev` as the working branch.
4. To demonstrate a failed gate, open a disposable PR that changes the
   fixture overlay's `RELEVANCE_FLOOR` to `1.01`. The fixture emits no
   citations and `e2e-eval` fails. Capture the blocked merge state. Restore
   the floor in that same PR, wait for green CI, and capture the enabled
   merge state after the required review.
5. Save the two screenshots and the successful CD run link in
   `docs/evidence/`. Check that Docker Hub shows all three tags for the
   SHA from that run.


## Independent feature pull requests

Create each feature branch from the latest dev and open its PR against dev. The same
six CI jobs run before integration, while a subsequent push to dev validates the
combined result. Wait for green checks and a partner review before merging. Main's
existing protection remains in force for release PRs; this workflow change does not
itself add a protection rule to dev.

Independent PRs can stay open while waiting for review. Keep their file ownership
separate; after one merges, bring current target-branch changes into the next PR and
rerun CI when its tested contents change. A PR that depends on another PR must wait
for that prerequisite or explicitly use a stacked branch arrangement.

CD still runs only on a push to main. Feature PR checks build and scan images but do
not publish them or deploy a persistent real-corpus service.
