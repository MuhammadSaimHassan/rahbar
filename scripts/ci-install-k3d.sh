#!/usr/bin/env bash
set -euo pipefail
version=v5.9.0
base="https://github.com/k3d-io/k3d/releases/download/$version"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cd "$work"
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors "$base/k3d-linux-amd64" -o k3d-linux-amd64
curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors "$base/checksums.txt" -o checksums.txt
expected=$(awk '$2 == "_dist/k3d-linux-amd64" { print $1 }' checksums.txt)
if [[ -z "$expected" ]]; then echo "k3d-linux-amd64 not listed in checksums.txt" >&2; exit 1; fi
echo "$expected  k3d-linux-amd64" | sha256sum --check
mkdir -p "$HOME/.local/bin"
install -m 0755 k3d-linux-amd64 "$HOME/.local/bin/k3d"
if [[ -n "${GITHUB_PATH:-}" ]]; then echo "$HOME/.local/bin" >> "$GITHUB_PATH"; fi
