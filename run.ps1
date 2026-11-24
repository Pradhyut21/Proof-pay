# PanelProof entry point for Windows PowerShell.   .\run.ps1 <command>
param([Parameter(Position = 0)][string]$Command = "help", [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
. "$PSScriptRoot\scripts\common.ps1"
if (-not $env:PANELPROOF_REVEAL_TOKEN) { $env:PANELPROOF_REVEAL_TOKEN = "local-dev-token-0123" }

function Invoke-InWeb([string[]]$Cmd) {
    Push-Location "$script:Root\apps\web"
    try { Invoke-Native $Cmd } finally { Pop-Location }
}

switch ($Command) {
    "bootstrap" { & "$PSScriptRoot\scripts\bootstrap.ps1" }
    "check" {
        Invoke-Native @("cargo", "fmt", "--all", "--", "--check")
        Invoke-Native @("cargo", "clippy", "--locked", "--workspace", "--all-targets", "--", "-D", "warnings")
        Invoke-Native @("cargo", "test", "--locked", "--workspace")
        Invoke-Native ($script:Py + @("-m", "ruff", "check", "python", "scripts"))
        Invoke-Native ($script:Py + @("-m", "pytest", "-q", "python/tests"))
        foreach ($s in "lint", "typecheck", "format:check", "test", "build") { Invoke-InWeb @("pnpm", $s) }
    }
    "fmt" {
        Invoke-Native @("cargo", "fmt", "--all")
        Invoke-Native ($script:Py + @("-m", "ruff", "check", "--fix", "python", "scripts"))
        Invoke-InWeb @("pnpm", "format")
    }
    "smoke" { & "$PSScriptRoot\scripts\smoke.ps1" @Rest }
    "dataset" { & "$PSScriptRoot\scripts\build_dataset.ps1" @Rest }
    "audit" { & "$PSScriptRoot\scripts\audit_dataset.ps1" @Rest }
    "reproduce" { & "$PSScriptRoot\scripts\reproduce.ps1" @Rest }
    "api" {
        $dir = if ($Rest.Count -ge 1) { $Rest[0] } else { "data\demo" }
        $db = if ($Rest.Count -ge 2) { $Rest[1] } else { "data\runs\demo.sqlite" }
        New-Item -ItemType Directory -Force (Split-Path $db) | Out-Null
        Invoke-Native @("cargo", "run", "--locked", "-p", "panelproof-api", "--", $dir, $db)
    }
    "web" { Invoke-InWeb @("pnpm", "dev") }
    "e2e" { Invoke-InWeb @("pnpm", "build"); Invoke-InWeb @("pnpm", "e2e") }
    default {
        Write-Host "commands: bootstrap | check | fmt | smoke [--web] | dataset | audit | reproduce | api [dir sqlite] | web | e2e"
        Write-Host "  api serves data\demo on 127.0.0.1:3001; web serves the UI on 127.0.0.1:3000 (two terminals)"
    }
}
