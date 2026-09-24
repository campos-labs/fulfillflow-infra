[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Config,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][ValidateSet('status', 'resume', 'attempt', 'restore', 'pause')][string]$Mode,
    [ValidateSet('healthy', 'invalid-pool')][string]$Scenario,
    [string]$Source
)
$ErrorActionPreference = 'Stop'
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python unavailable.' }
    $arguments = @((Join-Path $PSScriptRoot 'a1.py'), '--config', $Config, '--output', $OutputDirectory, '--mode', $Mode)
    if ($Scenario) { $arguments += @('--scenario', $Scenario) }
    if ($Source) { $arguments += @('--source', $Source) }
    & $Python @arguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('A1 launcher failed; inspect executable and paths. No retry.')
    exit 2
}
