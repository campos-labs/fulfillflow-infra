param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw "Private directory unavailable: $PrivateDirectory" }
Push-Location $root
try {
    & (Join-Path $root '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'scale_calibration.py') --diagnostic --private $PrivateDirectory --output $OutputDirectory
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
