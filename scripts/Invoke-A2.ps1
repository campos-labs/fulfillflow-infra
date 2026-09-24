[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Config,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][ValidateSet('run', 'request', 'recover')][string]$Mode,
    [ValidateSet('explicit', 'auto')][string]$Condition,
    [ValidateSet('healthy', 'invalid-pool')][string]$Scenario,
    [ValidateSet('human', 'agent', 'script')][string]$Actor,
    [string]$Source
)
$ErrorActionPreference = 'Stop'
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python unavailable.' }
    $arguments = @((Join-Path $PSScriptRoot 'a2.py'), '--config', $Config, '--output', $OutputDirectory, '--mode', $Mode)
    if ($Condition) { $arguments += @('--condition', $Condition) }
    if ($Scenario) { $arguments += @('--scenario', $Scenario) }
    if ($Actor) { $arguments += @('--actor', $Actor) }
    if ($Source) { $arguments += @('--source', $Source) }
    & $Python @arguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('A2 launcher failed; inspect executable and paths. No retry.')
    exit 2
}
