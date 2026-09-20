[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$Kubectl,
    [string]$Terraform
)

$ErrorActionPreference = 'Stop'
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'Informe o caminho completo do Python preparado para este repositorio.'
    }
    $arguments = @((Join-Path $PSScriptRoot 'validate.py'), '--output', $OutputDirectory)
    if ($Kubectl) { $arguments += @('--kubectl', $Kubectl) }
    if ($Terraform) { $arguments += @('--terraform', $Terraform) }
    & $Python @arguments
    $childExit = $LASTEXITCODE
    if ($childExit -ne 0) {
        [Console]::Error.WriteLine("Validation stopped with exit code $childExit; no retry.")
    }
    exit $childExit
} catch {
    [Console]::Error.WriteLine('Validation launcher failed before completion; inspect executable and paths.')
    exit 2
}
