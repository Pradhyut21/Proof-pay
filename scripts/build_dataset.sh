#!/usr/bin/env bash
# Build the validated dataset (deterministic). Output: data/build/main (git-ignored).
set -euo pipefail
source "$(dirname "$0")/common.sh"
exec "${PP[@]}" build-dataset --config "${1:-configs/benchmark.yaml}" --out "${2:-data/build/main}"
