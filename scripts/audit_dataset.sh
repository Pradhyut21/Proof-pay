#!/usr/bin/env bash
# Audit a built dataset: leakage, duplicates, hashes and a byte-identical rebuild. Exit 1 on failure.
set -euo pipefail
source "$(dirname "$0")/common.sh"
exec "${PP[@]}" audit-dataset --dataset "${1:-data/build/main}" --rebuild-config configs/benchmark.yaml --workers 4 --out "${2:-data/build/audit_result.json}"
