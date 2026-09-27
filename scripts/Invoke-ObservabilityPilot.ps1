[CmdletBinding()]
param([switch]$Resume)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$private = Join-Path $env:LOCALAPPDATA 'FulfillFlowInfra\observability-01'
$source = Join-Path $root 'artifacts\observability-pilot-01'
$output = if ($Resume) { Join-Path $root 'artifacts\observability-pilot-02' } else { $source }
$python = Join-Path $root '.venv\Scripts\python.exe'
$docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python do repositorio indisponivel.' }
if (((Test-Path -LiteralPath $private) -and -not $Resume) -or (Test-Path -LiteralPath $output)) {
    throw 'Destino ja existe. Preserve os arquivos e envie para revisao; nao repetir automaticamente.'
}
Write-Host 'PREPARACAO: feche Codex, navegadores e IDEs. Mantenha Docker, internet e tomada. Inicio em 45 segundos.'
Start-Sleep -Seconds 45
$running = @(& $docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Docker indisponivel.' }
$historical = 'fulfillflow-local-01-control-plane'
if (@($running | Where-Object { $_ -ne $historical }).Count) { throw 'Outros containers ativos. Nenhuma alteracao realizada.' }
if ($historical -in $running) {
    & $docker stop --timeout 30 $historical
    if ($LASTEXITCODE -ne 0) { throw 'Parada do no historico nao confirmada.' }
}
Write-Host 'JANELA CRITICA: ambiente novo, um evento saudavel, sem escala e sem retries. Volumes preservados.'
$extra = if ($Resume) { @('--resume-from', $source) } else { @() }
$oldMode = $env:FULFILLFLOW_SCALE_ENVIRONMENT
$env:FULFILLFLOW_SCALE_ENVIRONMENT = 'observability-v1'
Push-Location $root
try {
    & $python (Join-Path $PSScriptRoot 'observability_pilot.py') --private $private --output $output @extra
    $result = $LASTEXITCODE
} finally {
    Pop-Location
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = $oldMode
}
$shutdown = Join-Path $output 'shutdown.json'
if ((Test-Path -LiteralPath $shutdown) -and ((Get-Content -LiteralPath $shutdown -Raw | ConvertFrom-Json).container_stopped -eq $true)) {
    Write-Host 'JANELA ENCERRADA: no parado; volumes e evidencias preservados. Envie o resumo, sem repetir.'
} else {
    Write-Warning 'Confira o resumo: encerramento nao confirmado ou execucao recusada antes de criar o no.'
}
exit $result
