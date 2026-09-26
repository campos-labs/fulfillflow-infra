param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('Check','Prepare','Calibrate')][string]$Mode = 'Check'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run uv sync --frozen --group autoscaling first.' }
Push-Location $root
try {
    if ($Mode -eq 'Calibrate') {
        & $python (Join-Path $PSScriptRoot 'scale_calibration.py') --private $PrivateDirectory --output $OutputDirectory
    } elseif ($Mode -eq 'Prepare') {
        & $python (Join-Path $PSScriptRoot 'scale_environment.py') --private $PrivateDirectory --output $OutputDirectory
    } else {
        & $python (Join-Path $PSScriptRoot 'scale_environment.py') --private $PrivateDirectory --output $OutputDirectory --check
    }
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
