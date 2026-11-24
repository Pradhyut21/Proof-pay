# Build the validated dataset (deterministic). Output: data\build\main (git-ignored).
param([string]$Config = "configs\benchmark.yaml", [string]$Out = "data\build\main")
. "$PSScriptRoot\common.ps1"
Invoke-Pp @("build-dataset", "--config", $Config, "--out", $Out)
