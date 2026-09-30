#Requires -Version 7.2
<#
.SYNOPSIS
    Administrative decommission of the AI Governance lab, the inverse of bootstrap-lab.ps1. Dry run by default.

.DESCRIPTION
    Plans (default) or applies (-Execute) deletion of the resource groups that
    bootstrap-lab.ps1 creates and routine workflows have no right to remove:

    * Lab resource group rg-aigov-<env>. It must already be empty: run
      teardown.yml with execute=true first. Deleting it also removes the role
      assignments scoped to it and the manifest records (ARM deployments) that
      inventory tombstones, so the records are exported to
      outputs/decommission/<timestamp>/ before deletion.
    * Identity resource group rg-aigov-<env>-identity with the APIM
      user-assigned identity id-aigov-apim-<env> (skip with -KeepIdentity).

    Each group must carry the bootstrap ownership tag, have no locks, and hold
    nothing beyond what bootstrap created; otherwise the script refuses.

    Soft-deleted tombstones are listed, never purged. `lab_session.py purge`
    reads the manifest records in the lab resource group, so purge first if a
    name must be reused before its recovery period ends.

    Kept: app registrations and federated credentials, custom roles, the
    subscription-scope Preflight Reader assignment, and the GitHub environment
    and variables. Re-run bootstrap-lab.ps1 -Execute to restore the lab; it
    recreates both groups, a new identity, its role assignments, and updates the
    identity repository variables. Start the next session with a new generation.

.PARAMETER SubscriptionId
    Target subscription ID.

.PARAMETER EnvironmentName
    Short environment name used in resource names. Default: lab.

.PARAMETER KeepIdentity
    Keep the identity resource group and the APIM user-assigned identity.

.PARAMETER Execute
    Apply the planned deletions. Without it the script only reads state and prints the plan.

.EXAMPLE
    ./scripts/decommission-lab.ps1 -SubscriptionId <subscription-id>

.EXAMPLE
    ./scripts/decommission-lab.ps1 -SubscriptionId <subscription-id> -Execute
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string]$SubscriptionId,

    [ValidatePattern('^[a-z0-9]{2,8}$')]
    [string]$EnvironmentName = 'lab',

    [switch]$KeepIdentity,

    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$InformationPreference = 'Continue'

$LabResourceGroup = "rg-aigov-$EnvironmentName"
$IdentityResourceGroup = "rg-aigov-$EnvironmentName-identity"
$IdentityName = "id-aigov-apim-$EnvironmentName"
$IdentityResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$IdentityResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$IdentityName"
$ManifestPrefix = 'aigov-manifest-'
$OwnerTag = 'aigov-owner'
$OwnerValue = 'aigov-lab'
$ExportDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) "outputs/decommission/$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
$TombstoneLists = [ordered]@{
    apim      = "/subscriptions/$SubscriptionId/providers/Microsoft.ApiManagement/deletedservices?api-version=2024-05-01"
    cognitive = "/subscriptions/$SubscriptionId/providers/Microsoft.CognitiveServices/deletedAccounts?api-version=2024-10-01"
    workspace = "/subscriptions/$SubscriptionId/providers/Microsoft.OperationalInsights/deletedWorkspaces?api-version=2023-09-01"
}

$script:Plan = [System.Collections.Generic.List[object]]::new()

function Add-PlanEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Step,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$State
    )
    $script:Plan.Add([pscustomobject]@{ Step = $Step; State = $State; Target = $Target })
}

function Invoke-AzJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $raw = & az @Arguments --only-show-errors --output json 2>&1
    $exitCode = $LASTEXITCODE
    $errors = @($raw | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() })
    $text = (@($raw | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        if ($AllowFailure) { return $null }
        throw "az $($Arguments[0..([Math]::Min(2, $Arguments.Count - 1))] -join ' ') failed (exit $exitCode): $($errors -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return $text | ConvertFrom-Json -Depth 50
}

function Get-TagValue {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [AllowNull()][object]$Resource,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $Resource -or -not $Resource.PSObject.Properties['tags'] -or $null -eq $Resource.tags) { return '' }
    $tag = $Resource.tags.PSObject.Properties[$Name]
    if ($tag) { return [string]$tag.Value }
    return ''
}

function Test-ResourceGroup {
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string[]]$AllowedResourceId = @()
    )
    $group = Invoke-AzJson -Arguments @('group', 'show', '--name', $Name, '--subscription', $SubscriptionId) -AllowFailure
    if (-not $group) {
        Add-PlanEntry -Step 'resource-group' -Target $Name -State 'absent (nothing to delete)'
        return [pscustomobject]@{ Name = $Name; Exists = $false; Blockers = @() }
    }
    $blockers = [System.Collections.Generic.List[string]]::new()
    if ((Get-TagValue -Resource $group -Name $OwnerTag) -ne $OwnerValue) {
        $blockers.Add("missing ownership tag $OwnerTag=$OwnerValue")
    }
    $locks = @(Invoke-AzJson -Arguments @('lock', 'list', '--resource-group', $Name, '--subscription', $SubscriptionId) | Where-Object { $_ })
    if ($locks.Count -gt 0) { $blockers.Add("$($locks.Count) lock(s); locks are never removed automatically") }
    $allowed = @($AllowedResourceId | ForEach-Object { $_.ToLowerInvariant() })
    $resources = @(Invoke-AzJson -Arguments @('resource', 'list', '--resource-group', $Name, '--subscription', $SubscriptionId) | Where-Object { $_ })
    $unexpected = @($resources | Where-Object { $allowed -notcontains ([string]$_.id).ToLowerInvariant() })
    if ($unexpected.Count -gt 0) {
        $blockers.Add("unexpected resource(s): $(($unexpected | ForEach-Object { "$($_.type)/$($_.name)" }) -join ', ')")
    }
    $state = if ($blockers.Count -eq 0) { "plan: delete ($($resources.Count) bootstrap resource(s) inside)" } else { "refused: $($blockers -join '; ')" }
    Add-PlanEntry -Step 'resource-group' -Target $Name -State $state
    return [pscustomobject]@{ Name = $Name; Exists = $true; Blockers = @($blockers) }
}

function Get-ManifestRecord {
    [CmdletBinding()]
    [OutputType([object[]])]
    param()
    $deployments = @(Invoke-AzJson -Arguments @('deployment', 'group', 'list', '--resource-group', $LabResourceGroup, '--subscription', $SubscriptionId) -AllowFailure | Where-Object { $_ })
    $records = @($deployments | Where-Object { ([string]$_.name).StartsWith($ManifestPrefix) })
    Add-PlanEntry -Step 'manifest-records' -Target $LabResourceGroup -State "plan: export $($records.Count) record(s) before deletion"
    return $records
}

function Get-Tombstone {
    [CmdletBinding()]
    [OutputType([object[]])]
    param()
    $pattern = "-aigov-$EnvironmentName-"
    foreach ($kind in $TombstoneLists.Keys) {
        $page = Invoke-AzJson -Arguments @('rest', '--method', 'get', '--url', $TombstoneLists[$kind]) -AllowFailure
        if (-not $page) {
            Add-PlanEntry -Step 'tombstones' -Target $kind -State 'not listed (discovery failed)'
            continue
        }
        $items = if ($page.PSObject.Properties['value']) { @($page.value) } else { @() }
        foreach ($item in @($items | Where-Object { $_ -and ([string]$_.name).Contains($pattern) })) {
            $properties = if ($item.PSObject.Properties['properties']) { $item.properties } else { $null }
            $purge = if ($properties -and $properties.PSObject.Properties['scheduledPurgeDate']) { $properties.scheduledPurgeDate } else { 'unknown' }
            Add-PlanEntry -Step 'tombstones' -Target "$kind/$($item.name)" -State "kept (soft-deleted; scheduled purge $purge)"
            [pscustomobject]@{ kind = $kind; name = $item.name; scheduled_purge = $purge }
        }
    }
}

# ---- Preconditions ----------------------------------------------------------

if ($env:GITHUB_ACTIONS -eq 'true') {
    throw 'decommission-lab.ps1 is administrator-only and refuses to run in GitHub Actions.'
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Required tool 'az' is not on PATH."
}
if (-not (Invoke-AzJson -Arguments @('account', 'show', '--subscription', $SubscriptionId) -AllowFailure)) {
    throw "Sign in with 'az login' to a tenant that contains subscription $SubscriptionId; the plan needs live state."
}
if (-not $Execute) {
    Write-Information 'Dry run: no changes will be made. Re-run with -Execute to apply.'
}

# ---- Plan ---------------------------------------------------------------------

$groups = [System.Collections.Generic.List[object]]::new()
$groups.Add((Test-ResourceGroup -Name $LabResourceGroup))
if ($KeepIdentity) {
    Add-PlanEntry -Step 'resource-group' -Target $IdentityResourceGroup -State 'kept (-KeepIdentity)'
}
else {
    $groups.Add((Test-ResourceGroup -Name $IdentityResourceGroup -AllowedResourceId $IdentityResourceId))
}
$records = if ($groups[0].Exists) { @(Get-ManifestRecord) } else { @() }
$tombstones = @(Get-Tombstone)

$refused = @($groups | Where-Object { $_.Blockers.Count -gt 0 })

# ---- Apply ----------------------------------------------------------------------

if ($Execute -and $refused.Count -eq 0 -and $PSCmdlet.ShouldProcess("subscription $SubscriptionId", 'Delete the AI Governance lab resource groups')) {
    if ($groups[0].Exists) {
        New-Item -ItemType Directory -Path $ExportDirectory -Force | Out-Null
        ConvertTo-Json -InputObject $records -Depth 50 | Set-Content -LiteralPath (Join-Path $ExportDirectory 'manifest-records.json') -Encoding utf8
        ConvertTo-Json -InputObject $tombstones -Depth 5 | Set-Content -LiteralPath (Join-Path $ExportDirectory 'tombstones.json') -Encoding utf8
        Add-PlanEntry -Step 'manifest-records' -Target $ExportDirectory -State "exported $($records.Count) record(s)"
    }
    # The lab group goes first: its role assignments reference the identity.
    foreach ($group in @($groups | Where-Object { $_.Exists })) {
        Write-Information "[apply] delete resource group $($group.Name)"
        Invoke-AzJson -Arguments @('group', 'delete', '--name', $group.Name, '--subscription', $SubscriptionId, '--yes') | Out-Null
        $still = Invoke-AzJson -Arguments @('group', 'exists', '--name', $group.Name, '--subscription', $SubscriptionId)
        $state = if ($still) { 'error: still exists after delete' } else { 'deleted' }
        Add-PlanEntry -Step 'resource-group' -Target $group.Name -State $state
    }
}

# ---- Summary (nonsecret) --------------------------------------------------------

Write-Output ''
Write-Output "AI Governance lab decommission ($(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' }))"
Write-Output "  Lab RG:      $LabResourceGroup"
Write-Output "  Identity RG: $IdentityResourceGroup$(if ($KeepIdentity) { ' (kept)' })"
Write-Output ''
$script:Plan | Format-Table -AutoSize -Wrap | Out-String -Width 240 | Write-Output
if ($refused.Count -gt 0) {
    Write-Output 'Refused: fix the blockers above. For leftover lab resources, run teardown.yml with execute=true first.'
}
Write-Output 'Kept: app registrations, federated credentials, custom roles, the Preflight Reader assignment,'
Write-Output '  and the GitHub environment and variables. Re-run bootstrap-lab.ps1 -Execute to restore the lab,'
Write-Output '  then start the next session with a new AIGOV_GENERATION.'
if ($refused.Count -gt 0) { exit 1 }
