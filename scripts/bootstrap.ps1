# Check the toolchain and install locked dependencies. Run from any directory:  .\scripts\bootstrap.ps1
. "$PSScriptRoot\common.ps1"
$ok = $true
foreach ($t in @(
        @("cargo", "install Rust stable from https://rustup.rs (Windows needs MSVC build tools, or use WSL)"),
        @("node", "install Node.js 22 or newer"),
        @("pnpm", "npm install -g pnpm"))) {
    if (Test-Tool $t[0]) { Write-Host "ok      $($t[0])" } else { Write-Host "MISSING $($t[0]) - $($t[1])"; $ok = $false }
}
if (Test-Tool "uv") { Write-Host "ok      uv" } else { Write-Host "note    uv not found; using the active python (needs 3.11+ and: pip install -e python)" }
if (-not $ok) { Write-Host "bootstrap: install the missing tools above and rerun"; exit 1 }
if (Test-Tool "uv") { Invoke-Native @("uv", "sync", "--project", "python", "--python", "3.11", "--locked") }
Push-Location apps\web; try { Invoke-Native @("pnpm", "install", "--frozen-lockfile") } finally { Pop-Location }
Invoke-Native @("cargo", "fetch", "--locked")
Write-Host "bootstrap: done"
