# Rebuild the dataset, audit it, and write a DEMO ONLY report from the offline adapter.
param([string]$Out = "data\build\main")
. "$PSScriptRoot\common.ps1"
Invoke-Pp @("build-dataset", "--config", "configs\benchmark.yaml", "--out", $Out)
Invoke-Pp @("audit-dataset", "--dataset", $Out, "--rebuild-config", "configs\benchmark.yaml", "--workers", "4", "--out", "data\build\audit_result.json")
Invoke-Pp @("demo-attempts", "--dataset", $Out, "--out", "data\build\demo_attempts.jsonl")
Invoke-Pp @("metrics", "--tasks", $Out, "--attempts", "data\build\demo_attempts.jsonl", "--out", "data\build\demo_report")
$m = (Get-Content "$Out\manifest.json" -Raw | ConvertFrom-Json).manifest_sha256
Write-Host "reproduce: manifest $m"
Write-Host "reproduce: report at data\build\demo_report\report.md (DEMO ONLY)"
