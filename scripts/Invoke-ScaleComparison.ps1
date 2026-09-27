[CmdletBinding()]
param(
    [ValidateSet('All','Measure','Prepare','Qualify','Execute')][string]$Mode = 'All',
    [string]$PrivateDirectory,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'artifacts\scale-comparison-01' }
if (-not $PrivateDirectory) {
    $bases = @(
        (Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\FulfillFlowInfra'),
        (Join-Path $env:LOCALAPPDATA 'FulfillFlowInfra')
    )
    $base = $bases | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'scale-01') } | Select-Object -First 1
    if (-not $base) { throw 'Private base not found; provide PrivateDirectory explicitly outside the repository.' }
    $PrivateDirectory = Join-Path $base 'scale-comparison-01'
}
$previousEnvironment = $env:FULFILLFLOW_SCALE_ENVIRONMENT
Push-Location $root
try {
    $dirty = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw 'Checkout must be clean.' }
    $running = @(& docker ps --format '{{.Names}}')
    if ($LASTEXITCODE -ne 0) { throw 'Docker must be available.' }
    $historical = @('fulfillflow-local-01-control-plane','fulfillflow-scale-01-control-plane')
    if (@($running | Where-Object { $_ -notin $historical }).Count) { throw 'Concurrent containers: no measurement started.' }
    foreach ($node in $running) {
        Write-Host "Stopping historical node $node; volumes preserved."
        & docker stop --timeout 30 $node
        if ($LASTEXITCODE -ne 0) { throw 'Historical node shutdown failed.' }
    }
    if ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB -lt 5) { throw 'At least 5 GiB free host memory required.' }
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = 'comparison-v1'
    $stages = if ($Mode -eq 'All') { @('prepare','qualify','execute') } elseif ($Mode -eq 'Measure') { @('qualify','execute') } else { @($Mode.ToLowerInvariant()) }
    Write-Host 'JANELA CRITICA: notebook na tomada e reservado. Preparacao + qualificacao unica + ate 9 tentativas; sem retries.'
    foreach ($stage in $stages) {
        & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'scripts\scale_comparison.py') --private $PrivateDirectory --output (Join-Path $OutputDirectory $stage) --mode $stage
        if ($LASTEXITCODE -ne 0) { throw "Stopped at $stage. Preserve output and return for review; do not repeat automatically." }
    }
    Write-Host 'Campaign stages finished. Return the output for analysis; no additional campaign authorized.'
} finally {
    $env:FULFILLFLOW_SCALE_ENVIRONMENT = $previousEnvironment
    Pop-Location
    $state = & docker inspect --format '{{.State.Running}}' fulfillflow-scale-compare-01-control-plane 2>$null
    if ($LASTEXITCODE -eq 0 -and $state -eq 'false') { Write-Host 'JANELA ENCERRADA: no da campanha parado, volumes preservados.' }
    elseif ($LASTEXITCODE -eq 0) { Write-Warning 'Campaign node still running; review shutdown before further work.' }
}
