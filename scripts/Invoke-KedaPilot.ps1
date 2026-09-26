param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('Prepare','Execute')][string]$Mode = 'Prepare',
    [switch]$CapacityProfile
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw "Private directory unavailable: $PrivateDirectory" }
$arguments = @((Join-Path $PSScriptRoot 'scale_keda.py'), '--private', $PrivateDirectory, '--output', $OutputDirectory)
if ($CapacityProfile) { $arguments += '--capacity-profile' }
if ($Mode -eq 'Prepare') { $arguments += '--prepare-only' }
if ($CapacityProfile) { Write-Host 'JANELA CRITICA: mantenha o notebook na tomada e livre de outras atividades ate o encerramento.' }
Push-Location $root
try {
    & (Join-Path $root '.venv/Scripts/python.exe') @arguments
    $result = $LASTEXITCODE
    if ($CapacityProfile) {
        $shutdownPath = Join-Path $OutputDirectory 'shutdown.json'
        if ((Test-Path -LiteralPath $shutdownPath) -and ((Get-Content -LiteralPath $shutdownPath -Raw | ConvertFrom-Json).container_stopped -eq $true)) {
            Write-Host 'JANELA ENCERRADA: no parado. Confira o resumo antes de considerar a coleta valida.'
        } else { Write-Warning 'Encerramento do no nao confirmado; confira os registros antes de continuar.' }
    }
} finally { Pop-Location }
exit $result
