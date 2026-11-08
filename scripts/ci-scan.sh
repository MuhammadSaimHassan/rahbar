#!/usr/bin/env bash
set -euo pipefail

cache="${RUNNER_TEMP:-/tmp}/rahbar-trivy"
mkdir -p "$cache"
status=0
for image in "$@"; do
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
    -v "$cache:/root/.cache/trivy" aquasec/trivy:0.70.0 image \
    --image-src docker --no-progress --scanners vuln --ignore-unfixed --severity HIGH,CRITICAL \
    --exit-code 1 "$image" || status=1
done
exit "$status"
