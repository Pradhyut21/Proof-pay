# Dot-sourced by the other scripts. Resolves the Python command (uv when available, else the active python).
$ErrorActionPreference = "Stop"
$script:Root = Split-Path -Parent $PSScriptRoot
Set-Location $script:Root
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"

function Test-Tool([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

if (Test-Tool "uv") {
    $script:Py = @("uv", "run", "--project", "python", "--python", "3.11", "--locked", "python")
} else {
    $env:PYTHONPATH = "$script:Root\python\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
    $script:Py = @($(if (Test-Tool "python") { "python" } else { "py" }))
}

function Invoke-Native {
    param([string[]]$Command)
    & $Command[0] @($Command[1..($Command.Length - 1)])
    if ($LASTEXITCODE -ne 0) { throw "command failed ($LASTEXITCODE): $($Command -join ' ')" }
}

function Invoke-Pp {
    param([string[]]$Arguments)
    Invoke-Native ($script:Py + @("-m", "panelproof.cli") + $Arguments)
}
