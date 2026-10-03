<#
.SYNOPSIS
    Point your local .env and this terminal at the lab generation that is deployed right now.
.DESCRIPTION
    Reads the newest active generation's deployment outputs (read-only), writes the
    private root .env for interactive notebooks, and clears shell variables that would
    override or conflict with it (for example AIGOV_GENERATION loaded in Lab 00, or
    AIGOV_HEADLESS and SESSION_* left over from an automated session). Run it after
    every deployment or teardown, and before starting Jupyter.
.EXAMPLE
    ./scripts/sync-lab-env.ps1
    ./scripts/sync-lab-env.ps1 -Generation g05
#>
[CmdletBinding()]
param(
    [string]$Generation,
    [string]$ResourceGroup
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

$account = az account show --query "{name:name, id:id}" -o json 2>$null | ConvertFrom-Json
if (-not $account) { throw 'Azure CLI is not signed in. Run az login, then run this script again.' }
"Subscription: $($account.name)"

$pyArgs = @((Join-Path $PSScriptRoot 'lab_session.py'), 'local-env', '--wrapper-clears-shell')
if ($Generation) { $pyArgs += @('--generation', $Generation) }
if ($ResourceGroup) { $pyArgs += @('--resource-group', $ResourceGroup) }
python @pyArgs
if ($LASTEXITCODE -ne 0) { throw 'local-env failed; see the message above.' }

# Environment variables are process-wide, so clearing them here also clears them for this terminal.
$envFile = Join-Path $repoRoot '.env'
$fileKeys = Get-Content $envFile | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } |
    ForEach-Object { ($_ -split '=', 2)[0] }
$sessionKeys = 'AIGOV_HEADLESS', 'SESSION_ID', 'SESSION_MAX_ATTEMPTS', 'SESSION_MAX_RESERVED_TOKENS',
    'SESSION_MAX_ESTIMATED_USD', 'SESSION_DEADLINE_UTC'
$cleared = @($fileKeys + $sessionKeys | Sort-Object -Unique | Where-Object { Test-Path "Env:$_" })
$cleared | ForEach-Object { Remove-Item "Env:$_" }
if ($cleared) { "Cleared from this terminal: $($cleared -join ', ')" }

$deployed = (Get-Content $envFile | Where-Object { $_ -like 'AIGOV_GENERATION=*' }) -replace '^AIGOV_GENERATION=', ''
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $repoGeneration = gh variable get AIGOV_GENERATION 2>$null
    if ($LASTEXITCODE -eq 0 -and $repoGeneration -and $repoGeneration -ne $deployed) {
        Write-Warning ("Repository variable AIGOV_GENERATION is '$repoGeneration' but '$deployed' is deployed. " +
            "Workflows run without -f generation would target the wrong generation. To fix it, run: " +
            "gh variable set AIGOV_GENERATION --body $deployed")
    }
}
"Ready: .env and this terminal now target generation $deployed. Restart Jupyter if it was already running."
