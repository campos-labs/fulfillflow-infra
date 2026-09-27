param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('Check','Prepare','Calibrate')][string]$Mode = 'Check'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run uv sync --frozen --group autoscaling first.' }
if ($Mode -eq 'Calibrate') {
    if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) {
        throw "Private directory unavailable in this session: $PrivateDirectory"
    }
    foreach ($name in @('identity.json', 'kubeconfig', 'values.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PrivateDirectory $name) -PathType Leaf)) {
            throw "Required private file unavailable: $name"
        }
    }
}
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
