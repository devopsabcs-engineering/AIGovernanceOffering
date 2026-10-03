<#
.SYNOPSIS
    Print the objective statuses from your most recent run of each lab notebook.
.EXAMPLE
    ./scripts/show-results.ps1
    ./scripts/show-results.ps1 -Notebook demo1-token-limits
#>
[CmdletBinding()]
param(
    [ValidateSet('00-setup-and-validation', 'demo1-token-limits', 'demo2-token-metrics', 'demo3-content-safety',
        'demo4-resilient-pool')]
    [string[]]$Notebook = @('00-setup-and-validation', 'demo1-token-limits', 'demo2-token-metrics',
        'demo3-content-safety', 'demo4-resilient-pool')
)
$ErrorActionPreference = 'Stop'
$root = Join-Path (Split-Path -Parent $PSScriptRoot) 'outputs/results'

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
