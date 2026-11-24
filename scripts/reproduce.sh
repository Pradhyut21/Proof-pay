#!/usr/bin/env bash
# Rebuild the dataset, audit it, and write a DEMO ONLY report from the offline adapter.
set -euo pipefail
source "$(dirname "$0")/common.sh"
OUT="${1:-data/build/main}"
"${PP[@]}" build-dataset --config configs/benchmark.yaml --out "$OUT"
"${PP[@]}" audit-dataset --dataset "$OUT" --rebuild-config configs/benchmark.yaml --workers 4 --out data/build/audit_result.json
"${PP[@]}" demo-attempts --dataset "$OUT" --out data/build/demo_attempts.jsonl
"${PP[@]}" metrics --tasks "$OUT" --attempts data/build/demo_attempts.jsonl --out data/build/demo_report
echo "reproduce: manifest $(python3 -c "import json;print(json.load(open('$OUT/manifest.json'))['manifest_sha256'])" 2>/dev/null || true)"
echo "reproduce: report at data/build/demo_report/report.md (DEMO ONLY)"
