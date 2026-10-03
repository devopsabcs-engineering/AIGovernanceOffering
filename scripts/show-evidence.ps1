<#
.SYNOPSIS
    Download a lab-session run's sanitized evidence and print its readiness and lab status tables.
.EXAMPLE
    ./scripts/show-evidence.ps1
    ./scripts/show-evidence.ps1 -RunId 36914471933 -OpenPng
#>
[CmdletBinding()]
param(
    [string]$RunId,
    [switch]$OpenPng,
    [switch]$PassThru
)
$ErrorActionPreference = 'Stop'

if (-not $RunId) {
    $RunId = gh run list --workflow lab-session.yml --limit 1 --json databaseId -q '.[0].databaseId'
}
$dir = Join-Path ([IO.Path]::GetTempPath()) "aigov-$RunId"
if (-not (Test-Path $dir)) {
    gh run download $RunId -D $dir
    if ($LASTEXITCODE -ne 0) { throw "gh run download $RunId failed" }
}

$file = Get-ChildItem $dir -Recurse -Filter evidence.json | Select-Object -First 1
if (-not $file) { throw "No evidence.json in run $RunId (sanitize may have failed closed)" }
$e = Get-Content $file.FullName -Raw | ConvertFrom-Json

"Session $($e.session_id) | $($e.phase) | $($e.generated_at)"
if ($e.readiness.checks -and @($e.readiness.checks.PSObject.Properties).Count) {
    'Readiness checks'
    $e.readiness.checks.PSObject.Properties |
        ForEach-Object { [pscustomobject]@{ check = $_.Name; status = $_.Value.status; attempts = $_.Value.attempts } } |
        Format-Table -AutoSize | Out-String
}
'Lab status'
$e.labs.PSObject.Properties |
    ForEach-Object { [pscustomobject]@{ lab = $_.Name; status = $_.Value.status } } |
    Format-Table -AutoSize | Out-String

$showback = $e.showback
if ($showback -and $showback.interval) {
    $iso = { param($v) if ($v -is [datetime]) { $v.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") } else { "$v" } }
    "$($showback.label) | $(& $iso $showback.interval.start) to $(& $iso $showback.interval.end) (half-open UTC)"
    "coverage $($showback.coverage) | reconciliation $($showback.reconciliation_status) | snapshot $($showback.snapshot_id)"
    $showback.teams.PSObject.Properties |
        ForEach-Object { [pscustomobject]@{ team = $_.Name; prompt_tokens = $_.Value.prompt_tokens;
                completion_tokens = $_.Value.completion_tokens; estimated_usd = $_.Value.estimated_usd } } |
        Format-Table -AutoSize | Out-String
    "total estimated_usd $($showback.totals.estimated_usd) ($($showback.totals.status))"
}

$png = Get-ChildItem $dir -Recurse -Filter *.png
if ($png) { "PNG files: $(Split-Path $png[0].FullName -Parent)" }
if ($OpenPng) { $png | ForEach-Object { Invoke-Item $_.FullName } }
if ($PassThru) { $e }
