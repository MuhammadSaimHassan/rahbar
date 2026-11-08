# Hosted release and merge-gate evidence

All facts below were read from GitHub Actions and the public Docker Hub API on 2026-11-08.

## Merge to main and CD

- PR #1 (`dev` into `main`) was merged by Saim Hassan with "Create a merge commit".
- Release commit SHA: `3a53930b91aa7db24e40ab8ef25a72684f293b87`
- CD run: https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42474907543
  - `test`: passed (34s)
  - `build-push`: passed (1m47s)
  - `deploy`: passed (3m1s)

## Docker Hub images tagged with the full SHA

The public Docker Hub API returned HTTP 200 for each tag.

- https://hub.docker.com/r/saimhassan005/rahbar-api/tags?name=3a53930b91aa7db24e40ab8ef25a72684f293b87
- https://hub.docker.com/r/saimhassan005/rahbar-ui/tags?name=3a53930b91aa7db24e40ab8ef25a72684f293b87
- https://hub.docker.com/r/saimhassan005/rahbar-indexer/tags?name=3a53930b91aa7db24e40ab8ef25a72684f293b87

## Blocked and green merge gate (PR #2, demo only, never merged)

PR #2 (`eval-gate-demo`): https://github.com/MuhammadSaimHassan/rahbar/pull/2

| Step | Run | Result |
| --- | --- | --- |
| Relevance floor set to `1.01` | https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42468814959 | `e2e-eval` failed with `GATE FAILED` ("citation validity must be at least 95% and have citations to score"); merge blocked |
| Floor restored to `0.70`, retry flags added | https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42470151475 | all six required checks green; approved |

Screenshots: [blocked](eval-gate-blocked.png) and [green](eval-gate-green.png).

Another failed run on the same PR, https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42469601969,
is **not** a gate failure. It failed at the k3d download with HTTP 504 during a GitHub
release-download outage and cleared on its own. It is listed so the history is not
misread.

## Limits

- CI uses the deterministic fixture corpus, so these results do not measure real-model
  accuracy.
- Branch-protection settings evidence is not included here.


## Second release after evidence PR #3

Verified on 2026-11-08:

- PR #3 merged release/gate documentation into main.
- Release SHA: `622ff386867e35f118b477b8cc645d68d37928fb`
- CD run: https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42476095435
- Jobs: test, build-push and deploy all passed.

Matching public tags were verified for all three repositories:

- https://hub.docker.com/r/saimhassan005/rahbar-api/tags?name=622ff386867e35f118b477b8cc645d68d37928fb
- https://hub.docker.com/r/saimhassan005/rahbar-ui/tags?name=622ff386867e35f118b477b8cc645d68d37928fb
- https://hub.docker.com/r/saimhassan005/rahbar-indexer/tags?name=622ff386867e35f118b477b8cc645d68d37928fb

PR #2 has been converted to a draft and remains unmerged. The normal floor was
restored for the historical green run; retain both run links to explain the demo.
The current active branch rules are captured in branch-protection-api.json. Expanded
UI screenshots remain pending because browser automation could not initialize.
