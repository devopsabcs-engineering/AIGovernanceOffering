<#
.SYNOPSIS
    Start a lab-session or teardown workflow run with the right generation, open it for approval, and follow it.
.DESCRIPTION
    Picks the generation for you: the next unused one for dry-run, deploy-only, and full-session;
    the active one for run-existing, report-only, and teardown. Opens the run page so a reviewer can
    click "Review deployments" > "lab" > "Approve and deploy", then waits for the result. After a
    deployment it updates the AIGOV_GENERATION repository variable and runs sync-lab-env.ps1; after a
    run-existing or report-only session it prints the sanitized evidence.
.EXAMPLE
    ./scripts/run-lab-workflow.ps1 -Mode dry-run
    ./scripts/run-lab-workflow.ps1 -Mode deploy-only
    ./scripts/run-lab-workflow.ps1 -Mode run-existing
    ./scripts/run-lab-workflow.ps1 -Mode report-only -WindowStart 2026-10-03T14:00:00Z -WindowEnd 2026-10-03T15:00:00Z
    ./scripts/run-lab-workflow.ps1 -Mode teardown-plan
    ./scripts/run-lab-workflow.ps1 -Mode teardown
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('dry-run', 'deploy-only', 'full-session', 'run-existing', 'report-only', 'teardown-plan', 'teardown')]
    [string]$Mode,
    [string]$Generation,
    [switch]$KeepEnvironment,
    [string]$WindowStart,
    [string]$WindowEnd,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'

$resourceGroup = gh variable get AIGOV_LAB_RESOURCE_GROUP
if ($LASTEXITCODE -ne 0 -or -not $resourceGroup) { throw 'Could not read the AIGOV_LAB_RESOURCE_GROUP repository variable (gh auth login?).' }
$creating = $Mode -in 'dry-run', 'deploy-only', 'full-session'
if (-not $Generation) {
    $which = if ($creating) { '--next' } else { '--active' }
    $Generation = python (Join-Path $PSScriptRoot 'lab_session.py') generations $which --resource-group $resourceGroup
    if ($LASTEXITCODE -ne 0) { throw "Could not determine the generation: $Generation" }
    $Generation = "$Generation".Trim()
}
"Mode $Mode | generation $Generation | resource group $resourceGroup"

if ($Mode -like 'teardown*') {
    $workflow = 'teardown.yml'
    $execute = if ($Mode -eq 'teardown') { 'true' } else { 'false' }
    $inputs = @('-f', "confirm_resource_group=$resourceGroup", '-f', "generation=$Generation", '-f', "execute=$execute")
} else {
    $workflow = 'lab-session.yml'
    $inputs = @('-f', "mode=$Mode", '-f', "generation=$Generation", '-f', "confirm_resource_group=$resourceGroup")
    if ($KeepEnvironment) { $inputs += @('-f', 'keep_environment=true') }
    if ($Mode -eq 'report-only') {
        if (-not ($WindowStart -and $WindowEnd)) {
            $source = gh run list --workflow lab-session.yml --status success --limit 20 --json databaseId,displayTitle |
                ConvertFrom-Json | Where-Object { $_.displayTitle -match "run-existing|full-session" } |
                Select-Object -First 1
            if (-not $source) { throw 'No successful run-existing session to take a window from; pass -WindowStart and -WindowEnd.' }
            $evidence = & (Join-Path $PSScriptRoot 'show-evidence.ps1') -RunId $source.databaseId -PassThru |
                Select-Object -Last 1
            $iso = { param($v) if ($v -is [datetime]) { $v.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") } else { "$v" } }
            $WindowStart = & $iso $evidence.showback.interval.start
            $WindowEnd = & $iso $evidence.showback.interval.end
            if (-not ($WindowStart -and $WindowEnd)) { throw "Run $($source.databaseId) has no showback interval; pass -WindowStart and -WindowEnd." }
            "Report window from run $($source.databaseId): $WindowStart to $WindowEnd"
        }
        $inputs += @('-f', "report_window_start=$WindowStart", '-f', "report_window_end=$WindowEnd")
    }
}

$since = (Get-Date).ToUniversalTime().AddSeconds(-5)
gh workflow run $workflow @inputs
if ($LASTEXITCODE -ne 0) { throw "gh workflow run $workflow failed." }
$runId = $null
for ($i = 0; $i -lt 20 -and -not $runId; $i++) {
    Start-Sleep -Seconds 3
    $runId = gh run list --workflow $workflow --event workflow_dispatch --limit 5 --json databaseId,createdAt |
        ConvertFrom-Json | Where-Object { ([datetime]$_.createdAt).ToUniversalTime() -ge $since } |
        Select-Object -Last 1 -ExpandProperty databaseId
}
if (-not $runId) { throw "The $workflow run did not appear; check: gh run list --workflow $workflow" }
$url = gh run view $runId --json url -q .url
"Run $runId : $url"
'Approve it on the run page: Review deployments > lab > Approve and deploy.'
if (-not $NoBrowser) { Start-Process $url }

gh run watch $runId --interval 15 --exit-status
$ok = $LASTEXITCODE -eq 0
if (-not $ok) {
    Write-Warning "Run $runId did not succeed. Failed step logs: gh run view $runId --log-failed"
}

switch ($Mode) {
    { $_ -in 'deploy-only', 'full-session' } {
        if ($ok -and ($Mode -eq 'deploy-only' -or $KeepEnvironment)) {
            gh variable set AIGOV_GENERATION --body $Generation
            & (Join-Path $PSScriptRoot 'sync-lab-env.ps1') -Generation $Generation
        }
        if ($Mode -eq 'full-session') { & (Join-Path $PSScriptRoot 'show-evidence.ps1') -RunId $runId }
    }
    { $_ -in 'run-existing', 'report-only' } { & (Join-Path $PSScriptRoot 'show-evidence.ps1') -RunId $runId }
    { $_ -like 'teardown*' } {
        # The residual report stays on the runner; its summary lines are in the job log.
        gh run view $runId --log | Select-String -Pattern 'cleanup: ' |
            ForEach-Object { ($_.Line -split 'cleanup: ', 2)[1] } | ForEach-Object { "cleanup: $_" }
        python (Join-Path $PSScriptRoot 'lab_session.py') generations --resource-group $resourceGroup
    }
}
if (-not $ok) { exit 1 }
