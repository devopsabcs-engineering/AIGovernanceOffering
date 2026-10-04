<#
.SYNOPSIS
    Print the objective statuses from your most recent run of each lab notebook.
.DESCRIPTION
    With -Evidence, builds sanitized evidence from those runs (the same sanitizer and renderer
    the lab-session workflow uses) and prints a lab status table. Labs 00, 06, and 07 only
    have evidence from workflow sessions; see show-evidence.ps1.
.EXAMPLE
    ./scripts/show-results.ps1
    ./scripts/show-results.ps1 -Notebook demo1-token-limits
    ./scripts/show-results.ps1 -Evidence -OpenPng
#>
[CmdletBinding()]
param(
    [ValidateSet('00-setup-and-validation', 'demo1-token-limits', 'demo2-token-metrics', 'demo3-content-safety',
        'demo4-resilient-pool')]
    [string[]]$Notebook = @('00-setup-and-validation', 'demo1-token-limits', 'demo2-token-metrics',
        'demo3-content-safety', 'demo4-resilient-pool'),
    [switch]$Evidence,
    [switch]$OpenPng
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($Evidence -or $OpenPng) {
    python (Join-Path $PSScriptRoot 'render_evidence.py') local
    if ($LASTEXITCODE -ne 0) { exit 1 }
    if ($OpenPng) {
        Get-ChildItem (Join-Path $repoRoot 'outputs/evidence/local/png') -Filter *.png |
            Where-Object { $_.Name -match '^lab0[1-5]-' } | ForEach-Object { Invoke-Item $_.FullName }
    }
    return
}

$root = Join-Path $repoRoot 'outputs/results'
$rows = foreach ($name in $Notebook) {
    $file = Get-ChildItem $root -Recurse -Filter "$name.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $file) {
        [pscustomobject]@{ notebook = $name; objective = '-'; status = 'not run'; recorded_at = '' }
        continue
    }
    $data = Get-Content $file.FullName -Raw | ConvertFrom-Json
    foreach ($objective in $data.objectives.PSObject.Properties) {
        [pscustomobject]@{
            notebook    = $name
            objective   = $objective.Name
            status      = $objective.Value.status
            recorded_at = $objective.Value.recorded_at
        }
    }
}
$rows | Format-Table -AutoSize
