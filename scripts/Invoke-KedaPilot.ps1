param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('Prepare','Execute')][string]$Mode = 'Prepare'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw "Private directory unavailable: $PrivateDirectory" }
$arguments = @((Join-Path $PSScriptRoot 'scale_keda.py'), '--private', $PrivateDirectory, '--output', $OutputDirectory)
if ($Mode -eq 'Prepare') { $arguments += '--prepare-only' }
Push-Location $root
try {
    & (Join-Path $root '.venv/Scripts/python.exe') @arguments
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
