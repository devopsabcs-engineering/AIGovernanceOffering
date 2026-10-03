---
permalink: /labs/lab-00-environment
title: "Lab 00 - Deploy the lab environment"
description: "Plan, approve, and deploy the Basic v2 lab environment through a protected session, then read the manifest and readiness evidence."
nav_order: 10
---

**[Version française]({{ "/fr/labs/lab-00-environment" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

| Item | Value |
| --- | --- |
| **Duration** | 45 minutes, plus approval and provisioning time |
| **Level** | Intermediate |
| **Prerequisites** | Completed administrative bootstrap, reviewer rights on the `lab` GitHub environment, and an approved model tuple |

The environment is one resource group deployed from `infra/main.bicep`: an APIM Basic v2 instance with a user-assigned managed identity, one approved model deployment, an Azure AI Content Safety resource, a Log Analytics workspace, and workspace-based Application Insights. The platform API `ai-gateway-api` uses the backend `ai-gateway-foundry` and serves three team products: `team-retail`, `team-finance`, and `team-hr`.

> [!WARNING]
> Basic v2 is a conditional choice. Its gateway is a public endpoint with no inbound private endpoint and no private backend connectivity, so the deployment requires explicit approval of public exposure. When private networking is required, choose Standard v2 and validate that topology separately. Documented policy support is not proof of a working lab until the session evidence passes.

An administrator runs `scripts/bootstrap-lab.ps1` once, outside any workflow. It creates the lab resource group, a separate identity resource group holding the APIM user-assigned identity, the custom roles, the two federated deployment and runtime identities, and the protected `lab` environment. Workflows never run the bootstrap and never write role assignments.

## Learning Objectives

By the end of this lab, you will be able to:

* Explain what the administrative bootstrap creates and why workflows never run it
* Choose the `lab-session.yml` mode that matches the authority you intend to grant
* Read the preflight and what-if output of a dry run before you approve a paid deployment
* Explain how the manifest record limits later cleanup to resources this session created
* Interpret the readiness summary and the session budget envelope

## Exercises

### Exercise 0.1: Read the approved parameters

```powershell
Get-Content infra/main.bicepparam
```

Expected result: `chatModelName`, `chatModelVersion`, `chatDeploymentSku`, `chatDeploymentCapacity`, `aiLocation`, and `generation` have no defaults, and `allowGlobalProcessing` is `false`.

No model, version, SKU, region, or capacity is chosen for you. Canadian resource placement does not approve global inference processing, so preflight rejects Global deployment types unless `allowGlobalProcessing` is explicitly set.

### Exercise 0.2: Compile the templates without credentials

```powershell
az bicep build --file infra/main.bicep
az bicep build-params --file infra/main.bicepparam
```

Expected result: `az bicep build` succeeds without credentials and with no warnings other than documented suppressions. `az bicep build-params` succeeds only after every `AIGOV_*` variable listed in `infra/README.md` is set in your shell; until then it fails with `BCP427` and names the missing variable, so no model, region, or identity is ever guessed from source control.

To load the approved values into your shell, copy them from the repository variables the bootstrap and environment setup already wrote:

```powershell
gh variable list --json name,value | ConvertFrom-Json |
    Where-Object name -like 'AIGOV_*' |
    ForEach-Object { Set-Item "env:$($_.name)" $_.value }
az bicep build-params --file infra/main.bicepparam
```

Without GitHub access, set the variables directly. The model tuple below is the reference lab tuple; replace the bracketed values with the output of `scripts/bootstrap-lab.ps1`:

```powershell
$env:AIGOV_ENVIRONMENT_NAME          = 'lab'
$env:AIGOV_GENERATION                = '<generation>'
$env:AIGOV_NAME_SUFFIX               = '<name-suffix>'
$env:AIGOV_LOCATION                  = 'canadaeast'
$env:AIGOV_AI_LOCATION               = 'canadaeast'
$env:AIGOV_CONTENT_SAFETY_LOCATION   = 'canadaeast'
$env:AIGOV_PUBLISHER_EMAIL           = '<publisher-email>'
$env:AIGOV_PUBLISHER_NAME            = 'AI Governance Lab'
$env:AIGOV_APIM_IDENTITY_RESOURCE_ID = '/subscriptions/<subscription-id>/resourceGroups/rg-aigov-lab-identity/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-aigov-apim-lab'
$env:AIGOV_APIM_IDENTITY_CLIENT_ID   = '<apim-identity-client-id>'
$env:AIGOV_CHAT_MODEL_NAME           = 'gpt-4.1-mini'
$env:AIGOV_CHAT_MODEL_VERSION        = '2025-04-14'
$env:AIGOV_CHAT_DEPLOYMENT_SKU       = 'Standard'
$env:AIGOV_CHAT_DEPLOYMENT_CAPACITY  = '30'
$env:AIGOV_ALLOW_GLOBAL_PROCESSING   = 'false'
az bicep build-params --file infra/main.bicepparam
```

Compilation proves the templates are well formed. It does not prove quota, capacity, model eligibility, or that the policies behave as intended.

> [!NOTE]
> These commands leave `AIGOV_*` variables, including `AIGOV_GENERATION`, in your terminal. That is fine for compiling, but a stale `AIGOV_GENERATION` later conflicts with the `.env` file the notebooks use. Lab 01 runs `./scripts/sync-lab-env.ps1`, which clears them; opening a new terminal also works.

### Exercise 0.3: Choose a session mode

Each mode grants a different authority. Cleanup always acts only on resources recorded by the current session's own manifest.

| Mode | Deploys | Runs notebooks and traffic | Cleanup |
| --- | --- | --- | --- |
| `dry-run` | No | No | None; stops after preflight and what-if |
| `full-session` | Yes | Yes | On success and failure unless `keep_environment=true` |
| `deploy-only` | Yes | No | Only when deployment or readiness fails |
| `run-existing` | No; verifies the manifest | Yes | None; the environment is preserved |
| `report-only` | No; verifies the manifest | Showback report only | None; the environment is preserved |
| `lock-test` | No | No | None; rehearses the workflow lock without Azure |

Expected result: you can name the mode that preserves resources on failure (`run-existing` and `report-only`) and the only flag that keeps a `full-session` environment (`keep_environment=true`, which also reports continuing cost exposure).

### Exercise 0.4 (Hands-on): Run a dry run

Each deployment uses a new generation, a short label such as `g05` that appears in every resource name. A torn-down session leaves soft-deleted APIM, Cognitive Services, and Log Analytics names behind, so reusing its generation fails preflight with `tombstone_collision`. See which generations exist and which one comes next:

```powershell
az login
python scripts/lab_session.py generations
```

```text
Lab resource group: rg-aigov-lab
generation  state            records  last activity (UTC)
g03         retired                3  2026-09-30T12:45:48
g04         torn down              3  2026-10-01T19:37:16
active generation: none
next unused generation: g05
```

Start the dry run. The script picks the next unused generation, reads the resource group from the repository variable `AIGOV_LAB_RESOURCE_GROUP`, opens the run page, and follows the run until it ends:

```powershell
./scripts/run-lab-workflow.ps1 -Mode dry-run
```

On the run page that opens, select **Review deployments**, check **lab**, and select **Approve and deploy**. Every session waits for this approval.

Every session targets the existing lab resource group created by the bootstrap (`rg-aigov-lab` by default). No input selects another resource group; the workflow input `confirm_resource_group` is a safety check that must match that name exactly. The script fills it in for you. The equivalent raw command is:

```powershell
gh workflow run lab-session.yml -f mode=dry-run -f generation=<generation> -f confirm_resource_group=<resource-group>
```

Expected result: after approval, the session logs in with the deployment identity, runs preflight and what-if, and stops. No manifest record, deployment, or cleanup occurs.

Preflight checks the model tuple, provider registration, API Management regional availability, model quota, Content Safety availability, and soft-deleted APIM, Cognitive Services, and Log Analytics names that would collide. What-if fails on unexpected deletes or changes outside the planned resource IDs.

### Exercise 0.5 (Hands-on): Deploy and read readiness

Start a `deploy-only` session for the same generation and approve it. Like `full-session` and `run-existing`, it refuses to start unless the repository variable `AIGOV_PRICE_SNAPSHOT` points to an approved price snapshot file under `scripts/prices/`.

```powershell
./scripts/run-lab-workflow.ps1 -Mode deploy-only
```

The dry run created no manifest record, so the script picks the same generation again. Deployment and readiness take about 15 minutes. When the run succeeds, the script:

1. Sets the repository variable `AIGOV_GENERATION` to the new generation, so later workflow runs that omit a generation target the right one.
2. Runs `./scripts/sync-lab-env.ps1`, which writes your local `.env` from the deployment outputs for Lab 01.

A `deploy-only` session keeps the environment; cleanup runs only if deployment or readiness fails. To deploy, run every notebook, and keep the resources in one session, use `-Mode full-session -KeepEnvironment` instead. Kept resources continue to incur cost until a teardown.

The equivalent raw commands are:

```powershell
gh workflow run lab-session.yml -f mode=deploy-only -f generation=<generation> -f confirm_resource_group=<resource-group>
gh run watch (gh run list --workflow lab-session.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh variable set AIGOV_GENERATION --body <generation>
```

Expected result: the session writes an append-only manifest record named `aigov-manifest-<generation>-<session_id>-<hash8>` before any mutation, deploys incrementally, and writes `outputs/readiness/<session_id>/summary.json` with one status per check.

Readiness polls the gateway, the logger and diagnostic readback including custom-metric dimensions, the Content Safety account provisioning state, a model call through the platform API at `/ai-gateway`, and first metric ingestion. The first Content Safety call through the gateway happens in Lab 04. A readiness or scope-probe failure skips every notebook, traffic, and showback step; evidence and the mode's cleanup still run. The session envelope caps attempts, reserved tokens, estimated spend, and wall-clock time, and every model or safety call reserves against it before dispatch.

### Exercise 0.6: Review the session evidence

> [!NOTE]
> Reviewed evidence from session `36608221120-1` ([workflow run](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), rendered on 2026-09-29 from sanitized results only.

![Objective results for Lab 00 from the reviewed session]({{ '/assets/images/lab00-environment-summary.png' | relative_url }})

To view the same tables for your own session, download its sanitized evidence and print it:

```powershell
# Latest lab-session run
./scripts/show-evidence.ps1

# A specific run, and open the rendered PNG files
./scripts/show-evidence.ps1 -RunId <run-id> -OpenPng
```

The script downloads the run artifacts to a temporary folder with `gh run download`, reads `evidence.json`, and prints the readiness checks and the status of each lab. It reads sanitized evidence only and needs no Azure credentials.

```text
check                    status attempts
-----                    ------ --------
content_safety_account   passed        1
custom_metric_dimensions passed        1
diagnostic               passed        1
gateway                  passed        1
inference                passed        1
logger                   passed        1
metric_ingestion         passed       15
```

Expected result: after a `deploy-only` session, `lab00-environment` is `passed`, Labs 01 to 06 are `not_run`, and `lab07-teardown` is `kept`. Labs 01 to 05 run the notebooks yourself against this environment, and Lab 06 starts a `run-existing` session for the automated traffic and report.

## Validation Checklist

* [ ] The model tuple and generation are explicit and approved
* [ ] You approved public exposure for Basic v2 or chose Standard v2 for private networking
* [ ] A dry run completed and its what-if output matched the planned resources
* [ ] The manifest record exists before any deployed resource
* [ ] Every readiness check reports a status in the summary

## Knowledge Check

* Why does the bootstrap run once as an administrator instead of inside a workflow?
* Which modes can delete resources, and under which outcomes?
* What does a readiness failure skip, and what still runs?
* Why is a successful `az bicep build` not evidence that the lab works?

## Next Steps

Continue to [Lab 01: Setup and validation]({{ "/labs/lab-01-setup-validation" | relative_url }}).
