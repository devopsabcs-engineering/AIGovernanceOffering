#Requires -Version 7.2
<#
.SYNOPSIS
    One-time administrative bootstrap for the AI Governance lab. Dry run by default.

.DESCRIPTION
    Plans (default) or applies (-Execute) the administrative prerequisites that
    routine workflows must never hold rights to create:

    * Lab resource group rg-aigov-<env> and a separate identity resource group
      rg-aigov-<env>-identity with the APIM user-assigned identity id-aigov-apim-<env>.
    * Data-plane roles for that identity at lab resource group scope.
    * Custom roles "AIGov APIM Lab Operator" (lab resource group) and
      "AIGov Preflight Reader" (subscription) from scripts/roles/*.json, after
      verifying every action against the provider operation catalog.
    * Deploy and runtime app registrations, each with one federated credential
      bound to the protected GitHub environment "lab" (never a branch subject).
    * Role assignments with deterministic names.
    * The GitHub environment "lab" (required reviewers, main-only branch policy)
      and nonsecret repository variables.

    The script is idempotent: existing objects that already match are reported
    and left unchanged. It creates no client secrets and sets no GitHub secrets.

    Accepted residual risk (DD-06): any approved job that uses environment "lab"
    on main can obtain either identity. Only the lab-session cloud job and the
    teardown job use that environment, and code on main is reviewed.

.PARAMETER SubscriptionId
    Target subscription ID.

.PARAMETER Location
    Azure region for the resource groups and the user-assigned identity.

.PARAMETER EnvironmentName
    Short environment name used in resource names. Default: lab.

.PARAMETER Repository
    GitHub repository as owner/name. Defaults to the repository of the current directory.

.PARAMETER Reviewers
    GitHub user logins required to approve jobs in environment "lab". Required with -Execute.

.PARAMETER Subject
    Explicit OIDC subject override. It must be bound to environment "lab" and must not be a branch or pull request subject.

.PARAMETER Execute
    Apply the planned changes. Without it the script only reads state and prints the plan.

.EXAMPLE
    ./scripts/bootstrap-lab.ps1 -SubscriptionId <subscription-id> -Location canadacentral -Reviewers octocat

.EXAMPLE
    ./scripts/bootstrap-lab.ps1 -SubscriptionId <subscription-id> -Location canadacentral -Reviewers octocat -Execute
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string]$SubscriptionId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9]+$')]
    [string]$Location,

    [ValidatePattern('^[a-z0-9]{2,8}$')]
    [string]$EnvironmentName = 'lab',

    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,

    [string[]]$Reviewers = @(),

    [string]$Subject,

    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$InformationPreference = 'Continue'

$GitHubEnvironment = 'lab'
$OidcIssuer = 'https://token.actions.githubusercontent.com'
$OidcAudience = 'api://AzureADTokenExchange'
$RolesDirectory = Join-Path $PSScriptRoot 'roles'

# Built-in role definition IDs (public, stable across tenants).
$BuiltInRoles = @{
    'Cognitive Services OpenAI User' = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    'Cognitive Services User'        = 'a97b65f3-24c7-4388-baec-2e87135dc908'
    'Monitoring Metrics Publisher'   = '3913510d-42f4-4e42-8a64-420c390055eb'
    'Contributor'                    = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
    'Managed Identity Operator'      = 'f1a07417-d97a-45cb-824c-7a7467783830'
    'Reader'                         = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
    'Log Analytics Reader'           = '73c42c96-874c-492b-b04d-ab87d138a893'
    'Monitoring Reader'              = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
}

$LabResourceGroup = "rg-aigov-$EnvironmentName"
$IdentityResourceGroup = "rg-aigov-$EnvironmentName-identity"
$IdentityName = "id-aigov-apim-$EnvironmentName"
$DeployAppName = "aigov-$EnvironmentName-deploy"
$RuntimeAppName = "aigov-$EnvironmentName-runtime"
$FederatedCredentialName = "github-environment-$GitHubEnvironment"
$SubscriptionScope = "/subscriptions/$SubscriptionId"
$LabScope = "$SubscriptionScope/resourceGroups/$LabResourceGroup"
$IdentityResourceId = "$SubscriptionScope/resourceGroups/$IdentityResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$IdentityName"
$OwnershipTags = @('aigov-owner=aigov-lab', "aigov-environment=$EnvironmentName", 'aigov-managed-by=bootstrap-lab')

$script:Plan = [System.Collections.Generic.List[object]]::new()
$script:CanReadAzure = $false
$script:CanReadGitHub = $false

function Add-PlanEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Step,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$State
    )
    $script:Plan.Add([pscustomobject]@{ Step = $Step; State = $State; Target = $Target })
}

function Invoke-PlannedChange {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Step,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    if (-not $Execute) {
        Add-PlanEntry -Step $Step -Target $Target -State "plan: $Description"
        return $null
    }
    if ($PSCmdlet.ShouldProcess($Target, $Description)) {
        Write-Information "[apply] $Step : $Description ($Target)"
        $result = & $Action
        Add-PlanEntry -Step $Step -Target $Target -State "applied: $Description"
        return $result
    }
    Add-PlanEntry -Step $Step -Target $Target -State "skipped: $Description"
    return $null
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
    return $text | ConvertFrom-Json -Depth 20
}

function Invoke-GhJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$InputJson,
        [switch]$AllowFailure
    )
    if ($InputJson) {
        $raw = $InputJson | & gh @Arguments 2>&1
    }
    else {
        $raw = & gh @Arguments 2>&1
    }
    $exitCode = $LASTEXITCODE
    $errors = @($raw | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() })
    $text = (@($raw | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        if ($AllowFailure) { return $null }
        throw "gh $($Arguments[0..([Math]::Min(2, $Arguments.Count - 1))] -join ' ') failed (exit $exitCode): $($errors -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return $text | ConvertFrom-Json -Depth 20
}

function Get-OptionalProperty {
    [CmdletBinding()]
    [OutputType([object[]])]
    param(
        [AllowNull()][object]$InputObject,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $InputObject) { return @() }
    $property = $InputObject.PSObject.Properties[$Name]
    if (-not $property -or $null -eq $property.Value) { return @() }
    return @($property.Value | Where-Object { $null -ne $_ })
}

function Get-DeterministicGuid {
    [CmdletBinding()]
    [OutputType([guid])]
    param([Parameter(Mandatory)][string]$Seed)
    $bytes = [System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($Seed.ToLowerInvariant()))
    $guidBytes = [byte[]]$bytes[0..15]
    $guidBytes[7] = ($guidBytes[7] -band 0x0F) -bor 0x50
    $guidBytes[8] = ($guidBytes[8] -band 0x3F) -bor 0x80
    return [guid]::new($guidBytes)
}

function Get-NameSuffix {
    [CmdletBinding()]
    [OutputType([string])]
    param()
    $bytes = [System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes("$SubscriptionId/$LabResourceGroup".ToLowerInvariant()))
    return ([System.Convert]::ToHexString($bytes).Substring(0, 6)).ToLowerInvariant()
}

function Resolve-Repository {
    [CmdletBinding()]
    param()
    if ($Repository) {
        $info = Invoke-GhJson -Arguments @('api', "repos/$Repository")
    }
    else {
        $current = Invoke-GhJson -Arguments @('repo', 'view', '--json', 'nameWithOwner')
        $info = Invoke-GhJson -Arguments @('api', "repos/$($current.nameWithOwner)")
    }
    return [pscustomobject]@{
        FullName = $info.full_name
        Id       = $info.id
        Owner    = $info.owner.login
        OwnerId  = $info.owner.id
    }
}

function Assert-EnvironmentSubject {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -notmatch "(^|:)environment:$([regex]::Escape($GitHubEnvironment))(:|$)") {
        throw "OIDC subject '$Value' is not bound to environment '$GitHubEnvironment'."
    }
    if ($Value -match '(^|:)ref:' -or $Value -match 'pull_request') {
        throw "OIDC subject '$Value' contains a branch, tag, or pull request claim; only the environment subject is allowed."
    }
}

function Resolve-OidcSubject {
    [CmdletBinding()]
    [OutputType([string])]
    param([Parameter(Mandatory)][pscustomobject]$RepositoryInfo)
    if ($Subject) {
        Assert-EnvironmentSubject -Value $Subject
        return $Subject
    }
    $customization = Invoke-GhJson -Arguments @('api', "repos/$($RepositoryInfo.FullName)/actions/oidc/customization/sub") -AllowFailure
    if (-not $customization -or $customization.use_default) {
        $value = "repo:$($RepositoryInfo.FullName):environment:$GitHubEnvironment"
    }
    else {
        $claims = @{
            repo                = $RepositoryInfo.FullName
            repository          = $RepositoryInfo.FullName
            repository_owner    = $RepositoryInfo.Owner
            repository_owner_id = [string]$RepositoryInfo.OwnerId
            repository_id       = [string]$RepositoryInfo.Id
            environment         = $GitHubEnvironment
        }
        $parts = foreach ($key in $customization.include_claim_keys) {
            if (-not $claims.ContainsKey($key)) {
                throw "Custom OIDC claim '$key' cannot be derived from repository metadata; pass -Subject explicitly."
            }
            "${key}:$($claims[$key])"
        }
        $value = $parts -join ':'
    }
    Assert-EnvironmentSubject -Value $value
    return $value
}

function Initialize-ResourceGroup {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Name)
    if ($script:CanReadAzure) {
        $group = Invoke-AzJson -Arguments @('group', 'show', '--name', $Name, '--subscription', $SubscriptionId) -AllowFailure
        if ($group) {
            $state = if ($group.location -eq $Location) { 'exists' } else { "exists in $($group.location) (requested $Location; left unchanged)" }
            Add-PlanEntry -Step 'resource-group' -Target $Name -State $state
            return
        }
    }
    Invoke-PlannedChange -Step 'resource-group' -Target $Name -Description "create in $Location with ownership tags" -Action {
        Invoke-AzJson -Arguments (@('group', 'create', '--name', $Name, '--location', $Location, '--subscription', $SubscriptionId, '--tags') + $OwnershipTags) | Out-Null
    } | Out-Null
}

function Initialize-ApimIdentity {
    [CmdletBinding()]
    param()
    if ($script:CanReadAzure) {
        $identity = Invoke-AzJson -Arguments @('identity', 'show', '--name', $IdentityName, '--resource-group', $IdentityResourceGroup, '--subscription', $SubscriptionId) -AllowFailure
        if ($identity) {
            Add-PlanEntry -Step 'user-assigned-identity' -Target $IdentityName -State 'exists'
            return $identity
        }
    }
    return Invoke-PlannedChange -Step 'user-assigned-identity' -Target $IdentityName -Description "create in $IdentityResourceGroup" -Action {
        Invoke-AzJson -Arguments (@('identity', 'create', '--name', $IdentityName, '--resource-group', $IdentityResourceGroup, '--location', $Location, '--subscription', $SubscriptionId, '--tags') + $OwnershipTags)
    }
}

function Assert-RoleAction {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$Action)
    if (-not $script:CanReadAzure) {
        Add-PlanEntry -Step 'role-action-check' -Target "$($Action.Count) actions" -State 'not verified (no Azure session); -Execute verifies before creating roles'
        return
    }
    $known = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($namespace in ($Action | ForEach-Object { $_.Split('/')[0] } | Sort-Object -Unique)) {
        $catalog = Invoke-AzJson -Arguments @('provider', 'operation', 'show', '--namespace', $namespace)
        foreach ($operation in (Get-OptionalProperty -InputObject $catalog -Name 'operations')) { [void]$known.Add($operation.name) }
        foreach ($resourceType in (Get-OptionalProperty -InputObject $catalog -Name 'resourceTypes')) {
            foreach ($operation in (Get-OptionalProperty -InputObject $resourceType -Name 'operations')) { [void]$known.Add($operation.name) }
        }
    }
    $unknown = @($Action | Where-Object { -not $known.Contains($_) })
    if ($unknown.Count -gt 0) {
        $message = "Unknown provider operations: $($unknown -join ', '). Fix scripts/roles/*.json before creating roles."
        if ($Execute) { throw $message }
        Write-Warning $message
        Add-PlanEntry -Step 'role-action-check' -Target ($unknown -join ', ') -State 'unknown action (would stop -Execute)'
    }
}

function Initialize-CustomRole {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FileName,
        [Parameter(Mandatory)][string]$AssignableScope
    )
    $definition = Get-Content -LiteralPath (Join-Path $RolesDirectory $FileName) -Raw | ConvertFrom-Json
    $definition.AssignableScopes = @($AssignableScope)
    Assert-RoleAction -Action $definition.Actions

    $existing = $null
    if ($script:CanReadAzure) {
        $existing = @(Invoke-AzJson -Arguments @('role', 'definition', 'list', '--name', $definition.Name, '--custom-role-only', 'true', '--scope', $SubscriptionScope)) | Select-Object -First 1
    }
    if ($existing) {
        $currentActions = @($existing.permissions[0].actions | Sort-Object)
        $wantedActions = @($definition.Actions | Sort-Object)
        $sameActions = -not (Compare-Object -ReferenceObject $currentActions -DifferenceObject $wantedActions)
        $sameScopes = -not (Compare-Object -ReferenceObject @($existing.assignableScopes) -DifferenceObject @($AssignableScope))
        if ($sameActions -and $sameScopes) {
            Add-PlanEntry -Step 'custom-role' -Target $definition.Name -State 'exists (actions match)'
            return $existing.name
        }
        $definition | Add-Member -NotePropertyName 'Id' -NotePropertyValue $existing.name -Force
        Invoke-PlannedChange -Step 'custom-role' -Target $definition.Name -Description 'update actions and assignable scope' -Action {
            $file = New-TemporaryFile
            try {
                $definition | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $file -Encoding utf8
                Invoke-AzJson -Arguments @('role', 'definition', 'update', '--role-definition', "@$file") | Out-Null
            }
            finally { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
        } | Out-Null
        return $existing.name
    }
    $created = Invoke-PlannedChange -Step 'custom-role' -Target $definition.Name -Description "create with scope $AssignableScope" -Action {
        $file = New-TemporaryFile
        try {
            $definition | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $file -Encoding utf8
            Invoke-AzJson -Arguments @('role', 'definition', 'create', '--role-definition', "@$file")
        }
        finally { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
    }
    if ($created) { return $created.name }
    return $null
}

function Initialize-AppRegistration {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$DisplayName)
    $app = $null
    if ($script:CanReadAzure) {
        $found = @(Invoke-AzJson -Arguments @('ad', 'app', 'list', '--display-name', $DisplayName) | Where-Object { $_ -and $_.displayName -eq $DisplayName })
        if ($found.Count -gt 1) { throw "More than one app registration is named '$DisplayName'; resolve the ambiguity manually." }
        if ($found.Count -eq 1) {
            $app = $found[0]
            Add-PlanEntry -Step 'app-registration' -Target $DisplayName -State "exists (appId $($app.appId))"
        }
    }
    if (-not $app) {
        $app = Invoke-PlannedChange -Step 'app-registration' -Target $DisplayName -Description 'create single-tenant app registration (no client secret)' -Action {
            Invoke-AzJson -Arguments @('ad', 'app', 'create', '--display-name', $DisplayName, '--sign-in-audience', 'AzureADMyOrg')
        }
    }
    if (-not $app) {
        return [pscustomobject]@{ DisplayName = $DisplayName; AppId = $null; ObjectId = $null; PrincipalId = $null }
    }

    $principal = $null
    if ($script:CanReadAzure) {
        $principal = @(Invoke-AzJson -Arguments @('ad', 'sp', 'list', '--filter', "appId eq '$($app.appId)'")) | Select-Object -First 1
    }
    if ($principal) {
        Add-PlanEntry -Step 'service-principal' -Target $DisplayName -State 'exists'
    }
    else {
        $principal = Invoke-PlannedChange -Step 'service-principal' -Target $DisplayName -Description 'create service principal' -Action {
            Invoke-AzJson -Arguments @('ad', 'sp', 'create', '--id', $app.appId)
        }
    }
    return [pscustomobject]@{
        DisplayName = $DisplayName
        AppId       = $app.appId
        ObjectId    = $app.id
        PrincipalId = if ($principal) { $principal.id } else { $null }
    }
}

function Initialize-FederatedCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][pscustomobject]$App,
        [Parameter(Mandatory)][string]$OidcSubject
    )
    $body = [ordered]@{
        name        = $FederatedCredentialName
        issuer      = $OidcIssuer
        subject     = $OidcSubject
        audiences   = @($OidcAudience)
        description = "GitHub Actions environment '$GitHubEnvironment' only"
    }
    if (-not $App.ObjectId) {
        Add-PlanEntry -Step 'federated-credential' -Target "$($App.DisplayName)/$FederatedCredentialName" -State "plan: create subject $OidcSubject"
        return
    }
    $credentials = @()
    if ($script:CanReadAzure) {
        $credentials = @(Invoke-AzJson -Arguments @('ad', 'app', 'federated-credential', 'list', '--id', $App.ObjectId) | Where-Object { $_ })
    }
    foreach ($credential in $credentials) {
        if ($credential.subject -match '(^|:)ref:' -or $credential.subject -match 'pull_request') {
            throw "App '$($App.DisplayName)' has federated credential '$($credential.name)' with a branch, tag, or pull request subject. Remove it manually; this script never adds or keeps such trust."
        }
        if ($credential.name -ne $FederatedCredentialName) {
            Write-Warning "App '$($App.DisplayName)' has an additional federated credential '$($credential.name)' ($($credential.subject)); review it manually."
        }
    }
    $current = $credentials | Where-Object { $_.name -eq $FederatedCredentialName } | Select-Object -First 1
    if ($current -and $current.subject -eq $OidcSubject -and $current.issuer -eq $OidcIssuer -and (@($current.audiences) -join ',') -eq $OidcAudience) {
        Add-PlanEntry -Step 'federated-credential' -Target "$($App.DisplayName)/$FederatedCredentialName" -State "exists ($OidcSubject)"
        return
    }
    $verb = if ($current) { 'update' } else { 'create' }
    Invoke-PlannedChange -Step 'federated-credential' -Target "$($App.DisplayName)/$FederatedCredentialName" -Description "$verb subject $OidcSubject" -Action {
        $file = New-TemporaryFile
        try {
            $body | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $file -Encoding utf8
            if ($current) {
                Invoke-AzJson -Arguments @('ad', 'app', 'federated-credential', 'update', '--id', $App.ObjectId, '--federated-credential-id', $FederatedCredentialName, '--parameters', "@$file") | Out-Null
            }
            else {
                Invoke-AzJson -Arguments @('ad', 'app', 'federated-credential', 'create', '--id', $App.ObjectId, '--parameters', "@$file") | Out-Null
            }
        }
        finally { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
    } | Out-Null
}

function Initialize-RoleAssignment {
    [CmdletBinding()]
    param(
        [string]$PrincipalId,
        [Parameter(Mandatory)][string]$PrincipalLabel,
        [string]$RoleDefinitionId,
        [Parameter(Mandatory)][string]$RoleLabel,
        [Parameter(Mandatory)][string]$Scope
    )
    $target = "$RoleLabel -> $PrincipalLabel @ $Scope"
    if (-not $PrincipalId -or -not $RoleDefinitionId) {
        if ($Execute -and -not $WhatIfPreference) { throw "Cannot assign '$RoleLabel' to '$PrincipalLabel': principal or role definition was not created." }
        Add-PlanEntry -Step 'role-assignment' -Target $target -State 'plan: assign after principal and role exist'
        return
    }
    if ($script:CanReadAzure) {
        $existing = @(Invoke-AzJson -Arguments @('role', 'assignment', 'list', '--assignee', $PrincipalId, '--role', $RoleDefinitionId, '--scope', $Scope, '--subscription', $SubscriptionId) -AllowFailure | Where-Object { $_ })
        if ($existing.Count -gt 0) {
            Add-PlanEntry -Step 'role-assignment' -Target $target -State 'exists'
            return
        }
    }
    $assignmentName = Get-DeterministicGuid -Seed "$Scope|$PrincipalId|$RoleDefinitionId"
    Invoke-PlannedChange -Step 'role-assignment' -Target $target -Description "assign (name $assignmentName)" -Action {
        # New principals can take a short time to replicate; retry a bounded number of times.
        for ($attempt = 1; $attempt -le 12; $attempt++) {
            $result = Invoke-AzJson -Arguments @('role', 'assignment', 'create', '--assignee-object-id', $PrincipalId, '--assignee-principal-type', 'ServicePrincipal', '--role', $RoleDefinitionId, '--scope', $Scope, '--name', "$assignmentName", '--subscription', $SubscriptionId) -AllowFailure
            if ($result) { return }
            Start-Sleep -Seconds 10
        }
        throw "Role assignment '$target' did not succeed after 12 attempts."
    } | Out-Null
}

function Initialize-GitHubEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][pscustomobject]$RepositoryInfo,
        [string[]]$Reviewer = @()
    )
    $repo = $RepositoryInfo.FullName
    if ($Execute -and $Reviewer.Count -eq 0) {
        throw "-Reviewers must list at least one GitHub user to approve environment '$GitHubEnvironment'."
    }
    $reviewerEntries = @(foreach ($login in $Reviewer) {
            $user = if ($script:CanReadGitHub) { Invoke-GhJson -Arguments @('api', "users/$login") } else { $null }
            if ($script:CanReadGitHub -and -not $user) { throw "GitHub user '$login' was not found." }
            [ordered]@{ type = 'User'; id = if ($user) { $user.id } else { 0 } }
        })
    $environmentBody = [ordered]@{
        reviewers                = $reviewerEntries
        deployment_branch_policy = [ordered]@{ protected_branches = $false; custom_branch_policies = $true }
    } | ConvertTo-Json -Depth 5 -Compress

    Invoke-PlannedChange -Step 'github-environment' -Target "$repo/$GitHubEnvironment" -Description "set required reviewers ($($Reviewer -join ', ')) and custom branch policy" -Action {
        Invoke-GhJson -Arguments @('api', '--method', 'PUT', "repos/$repo/environments/$GitHubEnvironment", '--input', '-') -InputJson $environmentBody | Out-Null
    } | Out-Null

    $policies = @()
    if ($script:CanReadGitHub) {
        $policyList = Invoke-GhJson -Arguments @('api', "repos/$repo/environments/$GitHubEnvironment/deployment-branch-policies") -AllowFailure
        $policies = Get-OptionalProperty -InputObject $policyList -Name 'branch_policies'
    }
    $others = @($policies | Where-Object { -not ($_.name -eq 'main' -and $_.type -eq 'branch') })
    if ($others.Count -gt 0) {
        throw "Environment '$GitHubEnvironment' has branch policies other than main: $(($others | ForEach-Object name) -join ', '). Remove them manually."
    }
    if (-not ($policies | Where-Object { $_.name -eq 'main' })) {
        Invoke-PlannedChange -Step 'github-branch-policy' -Target "$repo/$GitHubEnvironment" -Description 'allow deployments from main only' -Action {
            Invoke-GhJson -Arguments @('api', '--method', 'POST', "repos/$repo/environments/$GitHubEnvironment/deployment-branch-policies", '--input', '-') -InputJson '{"name":"main","type":"branch"}' | Out-Null
        } | Out-Null
    }
    else {
        Add-PlanEntry -Step 'github-branch-policy' -Target "$repo/$GitHubEnvironment" -State 'exists (main)'
    }

    if ($Execute -and -not $WhatIfPreference) {
        $readBack = Invoke-GhJson -Arguments @('api', "repos/$repo/environments/$GitHubEnvironment")
        $reviewerRule = @(Get-OptionalProperty -InputObject $readBack -Name 'protection_rules' | Where-Object { $_.type -eq 'required_reviewers' })
        if ($reviewerRule.Count -eq 0 -or @(Get-OptionalProperty -InputObject $reviewerRule[0] -Name 'reviewers').Count -eq 0) {
            throw "Readback: environment '$GitHubEnvironment' has no required reviewers."
        }
        $branchPolicy = @(Get-OptionalProperty -InputObject $readBack -Name 'deployment_branch_policy')
        if ($branchPolicy.Count -eq 0 -or -not $branchPolicy[0].custom_branch_policies) {
            throw "Readback: environment '$GitHubEnvironment' does not restrict deployment branches."
        }
        Add-PlanEntry -Step 'github-environment' -Target "$repo/$GitHubEnvironment" -State 'readback ok (reviewers, main-only)'
    }
}

function Initialize-RepositoryVariable {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][pscustomobject]$RepositoryInfo,
        [Parameter(Mandatory)][System.Collections.Specialized.OrderedDictionary]$Variable
    )
    $repo = $RepositoryInfo.FullName
    $current = @{}
    if ($script:CanReadGitHub) {
        foreach ($item in @(Invoke-GhJson -Arguments @('variable', 'list', '--repo', $repo, '--json', 'name,value') -AllowFailure | Where-Object { $_ })) {
            $current[$item.name] = $item.value
        }
    }
    foreach ($name in $Variable.Keys) {
        $value = [string]$Variable[$name]
        if ([string]::IsNullOrEmpty($value)) {
            Add-PlanEntry -Step 'repository-variable' -Target $name -State 'plan: set once the value exists'
            continue
        }
        if ($current.ContainsKey($name) -and $current[$name] -eq $value) {
            Add-PlanEntry -Step 'repository-variable' -Target $name -State 'exists (value matches)'
            continue
        }
        Invoke-PlannedChange -Step 'repository-variable' -Target $name -Description "set to $value" -Action {
            & gh variable set $name --body $value --repo $repo | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "gh variable set $name failed." }
        } | Out-Null
    }
}

# ---- Preconditions ----------------------------------------------------------

foreach ($tool in 'az', 'gh') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required tool '$tool' is not on PATH."
    }
}

$account = Invoke-AzJson -Arguments @('account', 'show', '--subscription', $SubscriptionId) -AllowFailure
$script:CanReadAzure = [bool]$account
& gh auth status *> $null
$script:CanReadGitHub = ($LASTEXITCODE -eq 0)

if ($Execute) {
    if (-not $script:CanReadAzure) { throw "Sign in with 'az login' to a tenant that contains subscription $SubscriptionId before using -Execute." }
    if (-not $script:CanReadGitHub) { throw "Sign in with 'gh auth login' (repository admin) before using -Execute." }
    if (-not $PSCmdlet.ShouldProcess("subscription $SubscriptionId and repository", 'Apply AI Governance lab bootstrap')) {
        return
    }
}
else {
    Write-Information 'Dry run: no changes will be made. Re-run with -Execute to apply.'
    if (-not $script:CanReadAzure) { Write-Warning 'No Azure session for this subscription; Azure state is reported as planned without existence checks.' }
    if (-not $script:CanReadGitHub) { Write-Warning 'No GitHub CLI session; GitHub state is reported as planned without existence checks.' }
}

$tenantId = if ($account) { $account.tenantId } else { $null }
$repositoryInfo = if ($script:CanReadGitHub) { Resolve-Repository } else { [pscustomobject]@{ FullName = $Repository; Id = $null; Owner = $null; OwnerId = $null } }
if (-not $repositoryInfo.FullName) { throw 'Pass -Repository owner/name when the GitHub CLI is not signed in.' }
$oidcSubject = if ($script:CanReadGitHub -or $Subject) { Resolve-OidcSubject -RepositoryInfo $repositoryInfo } else { "repo:$($repositoryInfo.FullName):environment:$GitHubEnvironment (unverified default)" }
$nameSuffix = Get-NameSuffix

# ---- Azure resources ----------------------------------------------------------

Initialize-ResourceGroup -Name $LabResourceGroup
Initialize-ResourceGroup -Name $IdentityResourceGroup
$identity = Initialize-ApimIdentity

$identityPrincipalId = if ($identity) { $identity.principalId } else { $null }
$identityClientId = if ($identity) { $identity.clientId } else { $null }
foreach ($roleName in 'Cognitive Services OpenAI User', 'Cognitive Services User', 'Monitoring Metrics Publisher') {
    Initialize-RoleAssignment -PrincipalId $identityPrincipalId -PrincipalLabel $IdentityName -RoleDefinitionId $BuiltInRoles[$roleName] -RoleLabel $roleName -Scope $LabScope
}

$operatorRoleId = Initialize-CustomRole -FileName 'aigov-apim-lab-operator.json' -AssignableScope $LabScope
$preflightRoleId = Initialize-CustomRole -FileName 'aigov-preflight-reader.json' -AssignableScope $SubscriptionScope

# ---- Entra app registrations and trust ----------------------------------------

$deployApp = Initialize-AppRegistration -DisplayName $DeployAppName
$runtimeApp = Initialize-AppRegistration -DisplayName $RuntimeAppName
Initialize-FederatedCredential -App $deployApp -OidcSubject $oidcSubject
Initialize-FederatedCredential -App $runtimeApp -OidcSubject $oidcSubject

# Deploy identity (also the recovery identity, DD-08): no role-assignment write.
Initialize-RoleAssignment -PrincipalId $deployApp.PrincipalId -PrincipalLabel $DeployAppName -RoleDefinitionId $BuiltInRoles['Contributor'] -RoleLabel 'Contributor' -Scope $LabScope
Initialize-RoleAssignment -PrincipalId $deployApp.PrincipalId -PrincipalLabel $DeployAppName -RoleDefinitionId $BuiltInRoles['Managed Identity Operator'] -RoleLabel 'Managed Identity Operator' -Scope $IdentityResourceId
Initialize-RoleAssignment -PrincipalId $deployApp.PrincipalId -PrincipalLabel $DeployAppName -RoleDefinitionId $preflightRoleId -RoleLabel 'AIGov Preflight Reader' -Scope $SubscriptionScope

# Runtime identity: APIM child objects and telemetry reads only.
Initialize-RoleAssignment -PrincipalId $runtimeApp.PrincipalId -PrincipalLabel $RuntimeAppName -RoleDefinitionId $operatorRoleId -RoleLabel 'AIGov APIM Lab Operator' -Scope $LabScope
foreach ($roleName in 'Reader', 'Log Analytics Reader', 'Monitoring Reader') {
    Initialize-RoleAssignment -PrincipalId $runtimeApp.PrincipalId -PrincipalLabel $RuntimeAppName -RoleDefinitionId $BuiltInRoles[$roleName] -RoleLabel $roleName -Scope $LabScope
}

# ---- GitHub environment and repository variables -----------------------------

Initialize-GitHubEnvironment -RepositoryInfo $repositoryInfo -Reviewer $Reviewers

$variables = [ordered]@{
    AZURE_TENANT_ID                 = $tenantId
    AZURE_SUBSCRIPTION_ID           = $SubscriptionId
    AIGOV_ENVIRONMENT_NAME          = $EnvironmentName
    AIGOV_LOCATION                  = $Location
    AIGOV_LAB_RESOURCE_GROUP        = $LabResourceGroup
    AIGOV_IDENTITY_RESOURCE_GROUP   = $IdentityResourceGroup
    AIGOV_NAME_SUFFIX               = $nameSuffix
    AIGOV_DEPLOY_CLIENT_ID          = $deployApp.AppId
    AIGOV_RUNTIME_CLIENT_ID         = $runtimeApp.AppId
    AIGOV_APIM_IDENTITY_RESOURCE_ID = $IdentityResourceId
    AIGOV_APIM_IDENTITY_CLIENT_ID   = $identityClientId
}
Initialize-RepositoryVariable -RepositoryInfo $repositoryInfo -Variable $variables

# ---- Summary (nonsecret) --------------------------------------------------------

Write-Output ''
Write-Output "AI Governance lab bootstrap ($(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' }))"
Write-Output "  Repository:        $($repositoryInfo.FullName)"
Write-Output "  GitHub environment: $GitHubEnvironment"
Write-Output "  OIDC subject:      $oidcSubject"
Write-Output "  Lab RG:            $LabScope"
Write-Output "  Identity:          $IdentityResourceId"
Write-Output "  Name suffix:       $nameSuffix"
Write-Output ''
$script:Plan | Format-Table -AutoSize -Wrap | Out-String -Width 240 | Write-Output
Write-Output 'Not set here (Phase 6 decisions): AIGOV_GENERATION, AIGOV_AI_LOCATION, AIGOV_CONTENT_SAFETY_LOCATION,'
Write-Output '  AIGOV_PUBLISHER_EMAIL, AIGOV_CHAT_MODEL_NAME, AIGOV_CHAT_MODEL_VERSION, AIGOV_CHAT_DEPLOYMENT_SKU,'
Write-Output '  AIGOV_CHAT_DEPLOYMENT_CAPACITY, AIGOV_PRICE_SNAPSHOT (required for full-session, deploy-only, run-existing),'
Write-Output '  and optionally AIGOV_PUBLISHER_NAME and AIGOV_ALLOW_GLOBAL_PROCESSING.'
Write-Output 'Accepted residual risk (DD-06): approved jobs in environment "lab" on main can obtain either identity.'
