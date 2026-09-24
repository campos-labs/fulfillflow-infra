[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SettingsFile,
    [ValidateSet('Check', 'Execute')][string]$Mode = 'Check'
)
$ErrorActionPreference = 'Stop'
$previousSecret = $env:CARRIER_ALPHA_WEBHOOK_SECRET
$code = 2
try {
    $settings = Get-Content -Raw -LiteralPath $SettingsFile | ConvertFrom-Json
    foreach ($item in @($settings.python, $settings.config)) {
        if (-not [IO.Path]::IsPathRooted($item) -or -not (Test-Path -LiteralPath $item -PathType Leaf)) { throw 'Invalid executable/configuration path.' }
    }
    $arguments = @((Join-Path $PSScriptRoot 'a2_campaign.py'), '--config', $settings.config, '--output', $settings.output, '--expected-sha', $settings.expected_sha)
    if ($Mode -eq 'Execute') {
        $values = Get-Content -Raw -LiteralPath $settings.secret_file | ConvertFrom-Json
        if (-not $values.alpha) { throw 'Carrier secret unavailable.' }
        $env:CARRIER_ALPHA_WEBHOOK_SECRET = $values.alpha
    } else { $arguments += '--check-only' }
    & $settings.python @arguments
    $code = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('A2 comparison launcher failed. Check local settings and preserved diagnostics; do not retry automatically.')
} finally {
    $env:CARRIER_ALPHA_WEBHOOK_SECRET = $previousSecret
}
exit $code
