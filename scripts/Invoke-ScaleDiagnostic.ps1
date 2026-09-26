param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$ReuseTerminalReads
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw "Private directory unavailable: $PrivateDirectory" }
$diagnosticArgs = @()
if ($ReuseTerminalReads) { $diagnosticArgs += '--reuse-terminal-reads' }
Push-Location $root
try {
    & (Join-Path $root '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'scale_calibration.py') --diagnostic --private $PrivateDirectory --output $OutputDirectory @diagnosticArgs
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
