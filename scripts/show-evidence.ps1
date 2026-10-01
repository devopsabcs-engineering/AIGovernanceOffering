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
    [switch]$OpenPng
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
'Readiness checks'
$e.readiness.checks.PSObject.Properties |
    ForEach-Object { [pscustomobject]@{ check = $_.Name; status = $_.Value.status; attempts = $_.Value.attempts } } |
    Format-Table -AutoSize | Out-String
'Lab status'
$e.labs.PSObject.Properties |
    ForEach-Object { [pscustomobject]@{ lab = $_.Name; status = $_.Value.status } } |
    Format-Table -AutoSize | Out-String

$png = Get-ChildItem $dir -Recurse -Filter *.png
if ($png) { "PNG files: $(Split-Path $png[0].FullName -Parent)" }
if ($OpenPng) { $png | ForEach-Object { Invoke-Item $_.FullName } }
