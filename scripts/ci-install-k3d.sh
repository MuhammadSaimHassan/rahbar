#!/usr/bin/env bash
set -euo pipefail
version=v5.9.0
base="https://github.com/k3d-io/k3d/releases/download/$version"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cd "$work"
curl --fail --silent --show-error --location "$base/k3d-linux-amd64" -o k3d-linux-amd64
curl --fail --silent --show-error --location "$base/checksums.txt" -o checksums.txt
grep -E ' [ *]?k3d-linux-amd64$' checksums.txt | sha256sum --check
mkdir -p "$HOME/.local/bin"
install -m 0755 k3d-linux-amd64 "$HOME/.local/bin/k3d"
if [[ -n "${GITHUB_PATH:-}" ]]; then echo "$HOME/.local/bin" >> "$GITHUB_PATH"; fi
