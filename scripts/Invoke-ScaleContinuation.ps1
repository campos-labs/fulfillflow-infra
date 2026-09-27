[CmdletBinding()]
param(
    [ValidateSet('Check','Execute')][string]$Mode = 'Check',
    [string]$PrivateDirectory,
    [string]$OutputDirectory,
    [string]$SourceDirectory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'artifacts\scale-comparison-continuation-01' }
if (-not $PrivateDirectory) {
    $bases = @(
        (Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\FulfillFlowInfra'),
        (Join-Path $env:LOCALAPPDATA 'FulfillFlowInfra')
    )
    $base = $bases | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'scale-01') } | Select-Object -First 1
    if (-not $base) { throw 'Private base not found; provide PrivateDirectory explicitly outside the repository.' }
    $PrivateDirectory = Join-Path $base 'scale-comparison-01'
}
if (-not $SourceDirectory) { $SourceDirectory = Join-Path $root 'artifacts\scale-comparison-02\execute' }
$previousEnvironment = $env:FULFILLFLOW_SCALE_ENVIRONMENT
Push-Location $root
try {
    $dirty = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw 'Checkout must be clean.' }
    if ($Mode -eq 'Execute') {
        $running = @(& docker ps --format '{{.Names}}')
        if ($LASTEXITCODE -ne 0) { throw 'Docker must be available.' }
        $historical = @('fulfillflow-local-01-control-plane','fulfillflow-scale-01-control-plane')
        if (@($running | Where-Object { $_ -notin $historical }).Count) { throw 'Concurrent containers: no measurement started.' }
        foreach ($node in $running) {
            Write-Host "Stopping historical node $node; volumes preserved."
            & docker stop --timeout 30 $node
            if ($LASTEXITCODE -ne 0) { throw 'Historical node shutdown failed.' }
        }
    }
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = 'comparison-v1'
    if ($Mode -eq 'Execute') { Write-Host 'JANELA CRITICA: notebook reservado. Apenas posicoes pendentes; espera de memoria limitada; sem retries.' }
    & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'scripts\scale_continuation.py') --private $PrivateDirectory --source $SourceDirectory --output $OutputDirectory --mode $Mode.ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) { throw 'Continuation stopped. Preserve output and review before another command.' }
    Write-Host 'Requested operation finished. Preserve evidence.'
} finally {
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = $previousEnvironment
    Pop-Location
    if ($Mode -eq 'Execute') {
        $state = & docker inspect --format '{{.State.Running}}' fulfillflow-scale-compare-01-control-plane 2>$null
        if ($LASTEXITCODE -eq 0 -and $state -eq 'false') { Write-Host 'JANELA ENCERRADA: no da campanha parado, volumes preservados.' }
        elseif ($LASTEXITCODE -eq 0) { Write-Warning 'Campaign node still running; review shutdown before further work.' }
    }
}
