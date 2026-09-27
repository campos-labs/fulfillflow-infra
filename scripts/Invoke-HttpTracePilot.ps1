[CmdletBinding()]
param(
    [string]$PrivateDirectory,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'artifacts\observability-http-01' }
if (-not $PrivateDirectory) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'FulfillFlowInfra\observability-01'),
        (Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\FulfillFlowInfra\observability-01')
    ) | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'identity.json') }
    if (@($candidates).Count -ne 1) { throw 'Informe -PrivateDirectory: referencia privada ausente ou ambigua.' }
    $PrivateDirectory = @($candidates)[0]
}
$python = Join-Path $root '.venv\Scripts\python.exe'
$docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Saida ja existe. Preserve e envie para revisao.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Python do repositorio indisponivel.' }
Write-Host 'PREPARACAO: feche Codex, navegadores e IDEs. Docker, internet e tomada; inicio em 45 segundos. A CI sera conferida antes do Kind.'
Start-Sleep -Seconds 45
$running = @(& $docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Docker indisponivel.' }
$historical = 'fulfillflow-local-01-control-plane'
if (@($running | Where-Object { $_ -ne $historical }).Count) { throw 'Outros containers ativos. Nenhuma alteracao realizada.' }
if ($historical -in $running) {
    & $docker stop --timeout 30 $historical
    if ($LASTEXITCODE -ne 0) { throw 'Parada do no historico nao confirmada.' }
}
$oldMode = $env:FULFILLFLOW_SCALE_ENVIRONMENT
$env:FULFILLFLOW_SCALE_ENVIRONMENT = 'observability-v1'
Push-Location $root
try {
    Write-Host 'PRE-CHECK DA CI + JANELA RESERVADA: uma consulta GET; APIs historicas preservadas.'
    & $python (Join-Path $PSScriptRoot 'http_trace_pilot.py') --private $PrivateDirectory --output $OutputDirectory
    $result = $LASTEXITCODE
} finally {
    Pop-Location
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = $oldMode
}
$summary = Join-Path $OutputDirectory 'summary.json'
if ((Test-Path -LiteralPath $summary) -and ((Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json).container_stopped -eq $true)) {
    Write-Host 'JANELA ENCERRADA: no parado; volumes preservados. Envie o resumo, sem repetir.'
} else { Write-Warning 'Encerramento nao confirmado, ou preflight recusou a execucao. Envie a saida.' }
exit $result
