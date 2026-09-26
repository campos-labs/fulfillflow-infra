param(
    [Parameter(Mandatory=$true)][string]$PrivateDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$ReuseTerminalReads,
    [switch]$ControlledHost
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw "Private directory unavailable: $PrivateDirectory" }
$PrivateDirectory = (Resolve-Path -LiteralPath $PrivateDirectory).Path
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Output already exists; use a new identifier.' }
$diagnosticArgs = @()
if ($ReuseTerminalReads) { $diagnosticArgs += '--reuse-terminal-reads' }
if ($ControlledHost) {
    if (-not $ReuseTerminalReads) { throw 'ControlledHost requires ReuseTerminalReads' }
    $diagnosticArgs += '--controlled-host'
}
Write-Host 'JANELA CRITICA: mantenha o notebook na tomada e livre de outras atividades ate o encerramento.'
Push-Location $root
try {
    & (Join-Path $root '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'scale_calibration.py') --diagnostic --private $PrivateDirectory --output $OutputDirectory @diagnosticArgs
    $result = $LASTEXITCODE
    $shutdownPath = Join-Path $OutputDirectory 'shutdown.json'
    if ((Test-Path -LiteralPath $shutdownPath) -and ((Get-Content -LiteralPath $shutdownPath -Raw | ConvertFrom-Json).container_stopped -eq $true)) {
        Write-Host 'JANELA ENCERRADA: no parado. Confira o resumo antes de considerar a coleta valida.'
    } else {
        Write-Warning 'Encerramento do no nao confirmado; confira Docker e os registros antes de continuar.'
    }
} finally { Pop-Location }
exit $result
