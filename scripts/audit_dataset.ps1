# Audit a built dataset: leakage, duplicates, hashes and a byte-identical rebuild. Fails on any finding.
param([string]$Dataset = "data\build\main", [string]$Out = "data\build\audit_result.json")
. "$PSScriptRoot\common.ps1"
Invoke-Pp @("audit-dataset", "--dataset", $Dataset, "--rebuild-config", "configs\benchmark.yaml", "--workers", "4", "--out", $Out)
