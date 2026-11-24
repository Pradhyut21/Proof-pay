# One-command offline smoke: generate, verify, export, import into the API, attempt, report.
#   .\scripts\smoke.ps1 [--web]
# Windows without a C toolchain: build the API in WSL and set PP_API_BIN (Linux path) + PP_API_WSL_DISTRO.
. "$PSScriptRoot\common.ps1"
Invoke-Native ($script:Py + @("scripts\smoke.py") + $args)
