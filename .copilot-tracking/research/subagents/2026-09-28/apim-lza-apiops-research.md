<!-- markdownlint-disable-file -->

> Historical sibling-pattern snapshot, superseded on 2026-09-28 where it conflicts with .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. The primary defers APIOps publishing and requires explicit future ownership transfer; do not copy credentials, permissions, or deletion behavior from this inventory. Original content is retained as evidence; historical line references predate this notice.

# Research: APIM Landing Zone Accelerator (sibling repo) — Bicep + APIOps structure

Status: Complete (scoped to the questions asked)
Date: 2026-09-28
Sibling repo: `C:\src\GitHub\devopsabcs-engineering\APIM_apim-landing-zone-accelerator` (HEAD `591f5ba`, 2026-04-23, "fix: use reactive purge with backoff for soft-deleted Azure resources")
Consumer repo: `AIGovernanceOffering` (planning a simple APIM Basic v2 Bicep that must merge cleanly later)

## Research questions

1. Top-level tree and README summary.
2. APIM Bicep: module paths, SKUs, API version, VNet, managed identity, App Insights logger + diagnostics, named values, backends, backend pools, products, subscriptions, AI gateway scenario, policy fragments, token policies, naming.
3. APIOps: folder layout, `configuration.*.yaml` overrides, extractor/publisher workflows, tool version, policy/spec storage.
4. Workflows: triggers, auth variables, environment names.
5. Existing GenAI/OpenAI scenario details.

---

## 1. Top-level tree and README summary

Top level (dirs + notable files):

```text
.azuredevops/            ADO pipeline equivalents (apiops/, infra/deploy-apim-basicv2.yml, ...)
.github/workflows/       GitHub Actions (infra deploy, apps deploy, run-extractor-*, run-publisher-*)
artifacts/               APIOps artifact root (default/unscoped)
artifacts.dev-005/  artifacts.dev-005.api-team-00{1,2}/  artifacts.dev-005.merged/
artifacts.dev-006/  artifacts.dev-006.api-team-00{1,2}/   <- current BasicV2 instance
artifacts.prod/  artifacts.prod-005/  artifacts.prod-006/  artifacts.backup/
infra/
  api-management-basicv2/                         <- BasicV2/StandardV2 Bicep (instance 006)
    main.bicep, main.json, main.parameters.dev-006.json, main.parameters.prod-006.json
  api-management-create-with-external-vnet-publicip-stv2/  <- classic Developer/Premium + External VNet (instance 003/005/007)
    main.bicep, modules/{gateway,keyvault}.bicep, group/, identityProvider/, oauth-server/, subscription/, user/
  apim-b2c/ appservice/ fnapp/ webapp/ certificates/ scripts/ variables/ ExportedTemplate-*/
reference-implementations/AppGW-IAPIM-Func/bicep/{apim,backend,gateway,networking,shared}/  <- upstream LZA ref impl (Internal VNet + AppGW)
docs/ (APIOps lab guide), docsLZ/, src/ (backend apps), scripts/, tools/, aad/, b2c/, SampleArtifacts/
configuration.extractor[.dev-00X[.api-team-00Y]].yaml    <- extractor filters (root)
configuration.prod[-00X].yaml                           <- publisher per-env overrides (root)
mergeArtifacts.ps1, mergeAllArtifacts.ps1, policy.prod.xml, fed-cred.json, fed-cred-dev.json, .env.local
```

README summary (`README.md` lines 1-160):

* "Azure API Management landing zone accelerator with APIops automation, multi-environment CI/CD, and on-demand lab provisioning" (line 3).
* Current focus is BasicV2 instance `006` (dev + prod) deployed by `deploy-apim-basicv2.yml`; legacy instance `005` is Premium classic v1 with VNet and workspaces (README "APIM Instances" table).
* Quick start: 1) `Deploy APIM BasicV2` workflow, 2) `Deploy All Apps and APIs`, 3) `Run - Publisher - 006` with `publish-all-artifacts-in-repo`.
* It is a fork/derivative of upstream `Azure/apim-landing-zone-accelerator` (README "Related Resources"), but it does **not** contain the upstream `scenarios/` tree (no `scenarios/workload-genai`).

---

## 2. APIM Bicep

### 2.1 Module paths and SKUs

| Path | SKUs allowed | APIM API version | Network | Notes |
|---|---|---|---|---|
| `infra/api-management-basicv2/main.bicep` | `BasicV2`, `StandardV2` (lines 10-14, default `BasicV2`) | `Microsoft.ApiManagement/service@2024-06-01-preview` (line 48) | None (public) | Single flat file, no modules. Deployed by `.github/workflows/deploy-apim-basicv2.yml`. |
| `infra/api-management-create-with-external-vnet-publicip-stv2/main.bicep` (736 lines) | `Developer`, `Premium` (lines 10-14, default `Developer`) | `@2023-09-01-preview` (line 414) | `virtualNetworkType: 'External'` + `publicIpAddressId` + `subnetResourceId` (lines 433-436) | Also creates workspaces `workspace001/002` (lines 564-574) and self-hosted gateway module `modules/gateway.bicep` (lines 612, 649). |
| `reference-implementations/AppGW-IAPIM-Func/bicep/apim/apim.bicep` | `skuName` default `Developer` (line 23) | `@2021-08-01` (line 56) | `virtualNetworkType: 'Internal'` (line 73) | Upstream LZA ref impl (App Gateway in front of internal APIM). |

No `BasicV2` VNet integration or private endpoint option exists in the BasicV2 template.

### 2.2 BasicV2 template details (`infra/api-management-basicv2/main.bicep`)

Parameters (lines 3-39): `publisherEmail`, `publisherName`, `sku` (`BasicV2|StandardV2`), `skuCount`, `location`, `environmentName` (`@allowed dev|qa|prod`, line 22-28), `instanceNumber`, `createOAuth2Server`, `oAuth2ClientId`, `publisherPrincipalId`.

Naming (lines 41-46):

```bicep
var applicationInsightsLoggerName = 'apimlogger'
var baseName = 'apim-${environmentName}-${instanceNumber}-${uniqueString(resourceGroup().id)}'
var apiManagementName = baseName
var applicationInsightsName = 'appi-${baseName}'
var logAnalyticsWorkspaceName = 'log-${baseName}'
var keyVaultName = substring('kv-${baseName}', 0, 24)
```

Resource group names come from the workflow: `rg-apim-basicv2-dev-006`, `rg-apim-basicv2-prod-006` (`deploy-apim-basicv2.yml` lines 74-75). Resulting APIM names observed: `apim-dev-006-cxfqm7rkx4ppi`, `apim-prod-006-xcilqlmt7zdw2`.

APIM service (lines 48-74): SKU/capacity, `identity: { type: 'SystemAssigned' }` (lines 55-56), `apiVersionConstraint.minApiVersion: '2019-12-01'` (line 60), TLS 1.0/1.1/SSL3 disabled + HTTP/2 enabled via `customProperties`.

Observability (lines 76-125):

* Log Analytics `Microsoft.OperationalInsights/workspaces@2023-09-01`, PerGB2018, 90 days, `dailyQuotaGb: 1`.
* App Insights `Microsoft.Insights/components@2020-02-02`, workspace-based.
* Named value `instrumentationKey` (secret, value = AI instrumentation key) (lines 100-109).
* Logger `apimlogger`, `loggerType: 'applicationInsights'`, `credentials.instrumentationKey: '{{instrumentationKey}}'` (lines 111-125).
* **No `service/diagnostics` resource in Bicep** — diagnostics (`applicationinsights`, `azuremonitor`) are owned by APIOps artifacts, not Bicep.

Key Vault + RBAC (lines 127-179):

* KV RBAC mode; APIM MI gets **Key Vault Secrets User** (`4633458b-17de-408a-b874-0445c86b69e6`, line 155).
* Secret `AppInsightsKeyApim` stored (line 160).
* Optional: APIOps publisher SP gets **API Management Service Contributor** (`312a565d-c81f-4fd8-895a-4e21e48d571c`, line 175) on the APIM instance when `publisherPrincipalId` is set.

Optional OAuth2 authorization server `weatherappoauth` (lines 181-198).

Outputs (lines 200-204): `apiManagementName`, `apiManagementGatewayUrl`, `applicationInsightsName`, `keyVaultName`, `resourceGroupName`. The deploy workflow queries `properties.outputs.apiManagementName.value` and `apiManagementGatewayUrl.value` (workflow line 175).

Parameter files: `main.parameters.{dev|prod}-006.json` (ARM JSON params, not `.bicepparam`), e.g. dev: `sku=BasicV2`, `skuCount=1`, `environmentName=dev`, `instanceNumber=006`, `location=canadacentral`, `publisherPrincipalId=<guid>`.

### 2.3 What is NOT in Bicep (split of responsibilities)

Bicep owns only the platform: APIM service, MI, LAW, AI, `instrumentationKey` named value, `apimlogger` logger, KV, RBAC. Everything API-level — APIs, operations, policies, backends, products, subscriptions, groups, tags, version sets, diagnostics, policy fragments, other named values — is owned by **APIOps artifacts**. The extractor config explicitly excludes the Bicep-owned named value:

```yaml
# configuration.extractor.dev-006.yaml lines 45-47
namedValueNames:
  - developerPortalUrl
  #- instrumentationKey  # managed by Bicep template
```

### 2.4 Backends, pools, products, subscriptions, fragments, AI

* Backends: only plain URL backends (`backends/backend-weather-api/backendInformation.json`, `WebApp_fast-api-app-insights-001`). **No backend pools (`type: Pool`), no circuit breaker rules** anywhere (repo-wide search for `circuitBreaker`, `Pool`, `backend-pool` returned nothing).
* Products: `starter`, `unlimited`, `conference`, etc. as APIOps artifacts; product policies use classic `rate-limit` / `quota` (e.g. `artifacts.dev-006/products/starter/policy.xml`).
* Subscriptions: APIOps artifacts `subscriptions/<name>/subscriptionInformation.json` with `scope: "/products/starter"`, `ownerId: "/users/demo-admin"`. Demo subscriptions are seeded by `scripts/seed-apim-demo-data.ps1` (called from the deploy workflow line 264).
* Policy fragments: one sample `policy fragments/SampleEmptyPolicyFragment/{policy.xml,policyFragmentInformation.json}`; `policy.xml` root is `<fragment>...</fragment>`.
* **AI gateway / OpenAI / token policies: none.** Repo-wide search for `openai`, `llm-token`, `token-limit`, `emit-token`, `cognitiveservices`, `genai` across `*.bicep, *.xml, *.yaml, *.yml, *.json, *.md, *.kql` returned **zero matches**.

---

## 3. APIOps layout and configuration

### 3.1 Tool version

APIOps release `v6.0.2` (`env.apiops_release_version`, `run-extractor-006.yaml` line 41; `run-publisher-with-env-006.yaml` line 20). Binaries downloaded from `https://github.com/Azure/apiops/releases/download/<ver>/{extractor|publisher}-linux-x64.zip` and executed directly (no container, no action).

### 3.2 Artifact root folder naming

The repo does **not** use `apimartifacts/`. It uses `artifacts.<env>-<instance>[.<team>]` roots, selected at runtime via `API_MANAGEMENT_SERVICE_OUTPUT_FOLDER_PATH` (e.g. `artifacts.dev-006`). The folder name is purely a workflow input — APIOps does not care what the root is called.

### 3.3 Artifact folder format (APIOps v6, note the spaces in folder names)

Root-level `policy.xml` = global (All APIs) policy (`artifacts.dev-006/policy.xml`).

```text
artifacts.dev-006/
  policy.xml                                     # service-level policy
  apis/<apiName>/
    apiInformation.json                          # { "properties": { path, displayName, protocols, serviceUrl, subscriptionRequired, ... } }
    specification.yaml                           # OpenAPI v3 YAML (API_SPECIFICATION_FORMAT=OpenAPIV3Yaml)
    policy.xml                                   # API-level policy (only when non-default)
    operations/<operationName>/policy.xml        # operation-level policy
    diagnostics/applicationinsights/diagnosticInformation.json   # API-level diagnostic override
  backends/<backendName>/backendInformation.json
  diagnostics/{applicationinsights,azuremonitor}/diagnosticInformation.json
  groups/<group>/groupInformation.json
  loggers/{apimlogger,azuremonitor}/loggerInformation.json
  named values/<name>/namedValueInformation.json         # folder name has a SPACE
  policy fragments/<name>/{policy.xml,policyFragmentInformation.json}   # SPACE
  products/<product>/
    productInformation.json
    policy.xml
    apis/<apiName>/productApiInformation.json    # {} link file
    groups/<group>/productGroupInformation.json
  subscriptions/<name>/subscriptionInformation.json
  tags/<tag>/tagInformation.json
  version sets/<id>/versionSetInformation.json   # SPACE
  gateways/<name>/...                            # only in artifacts.prod (self-hosted gw)
```

Representative snippets:

```json
// artifacts.dev-006/backends/backend-weather-api/backendInformation.json
{ "properties": { "credentials": { "header": {}, "query": {} }, "description": "backend for weather api (DEV)",
  "protocol": "http", "tls": { "validateCertificateChain": false, "validateCertificateName": false },
  "url": "https://app-weather-api-wvwg5gngtozli.azurewebsites.net" } }
```

```json
// artifacts.dev-006/loggers/apimlogger/loggerInformation.json
{ "properties": { "loggerType": "applicationInsights", "credentials": { "instrumentationKey": "{{instrumentationKey}}" },
  "description": "Application Insights for APIM", "isBuffered": true,
  "resourceId": "/subscriptions/.../resourceGroups/rg-apim-vnet-external-dev-005-eu2/providers/Microsoft.Insights/components/appi-apim-dev-005-3snpbfdd5kffc" } }
```

Note: this logger `resourceId` points to the **dev-005** App Insights even inside `artifacts.dev-006` — drift caused by copying artifacts between instances. The Bicep-created logger is the real one.

```json
// artifacts.dev-006/diagnostics/applicationinsights/diagnosticInformation.json (abridged)
{ "properties": { "loggerId": ".../service/apim-dev-006-cxfqm7rkx4ppi/loggers/apimlogger",
  "alwaysLog": "allErrors", "httpCorrelationProtocol": "Legacy", "logClientIp": true,
  "sampling": { "percentage": 80, "samplingType": "fixed" }, "verbosity": "information", "frontend": {...}, "backend": {...} } }
```

```json
// named values: secret -> no value extracted; non-secret -> value included
{ "properties": { "displayName": "instrumentationKey", "secret": true, "tags": [] } }
{ "properties": { "displayName": "weatherApiAudience", "secret": false, "tags": [], "value": "e6b456e3-..." } }
```

API policy files reference backends by id and named values with `{{name}}`:

```xml
<!-- artifacts.dev-006/apis/weatherapi/policy.xml -->
<inbound>
  <base />
  <set-backend-service id="apim-generated-policy" backend-id="backend-weather-api" />
  <validate-jwt ...><audiences><audience>{{weatherApiAudience}}</audience></audiences>...</validate-jwt>
  <rate-limit-by-key calls="5" renewal-period="60" counter-key="@(context.Request.IpAddress)" />
</inbound>
```

### 3.4 Extractor filter config (`configuration.extractor.dev-006.yaml`)

Top-level keys (lines 4-68): `apiNames`, `tagNames`, `loggerNames`, `namedValueNames`, `productNames`, `backendNames`, `policyFragmentNames`. Team-scoped variants (`configuration.extractor.dev-006.api-team-001.yaml`) are the same file with entries commented out.

### 3.5 Publisher environment overrides (`configuration.<env>.yaml`)

`configuration.prod-006.yaml` top-level keys: `apimServiceName` (line 1), `namedValues` (2), `apis` (39), `products` (54), `policyFragments` (127), `tags` (131). Pattern is a list of `{ name, properties: {...} }` overlaid on the artifact JSON:

```yaml
apimServiceName: apim-prod-006-xcilqlmt7zdw2
namedValues:
  - name: testSecret
    properties:
      displayName: testSecret
      value: "{#testSecretValue#}"     # token replaced by cschleiden/replace-tokens from GH secret
  - name: weatherApiAudience
    properties: { displayName: weatherApiAudience, value: "7c0729e5-...", tags: [prod_api] }
```

Richer example with `loggers`, `diagnostics`, `backends`, `subscriptions`, `workspaces` overrides: `configuration.prod-005.yaml` (keys at lines 63, 72, 80, 114, 270):

```yaml
loggers:
  - name: apimlogger
    properties:
      loggerType: applicationInsights
      resourceId: "/subscriptions/.../providers/Microsoft.Insights/components/appi-apim-prod-005-..."
      credentials: { instrumentationKey: "{{instrumentationKey}}" }
diagnostics:
  - name: applicationInsights
    properties: { verbosity: Error, loggerId: ".../loggers/apimlogger", sampling: { samplingType: fixed, percentage: 67 } }
backends:
  - name: helloworldfromfuncapp
    properties: { url: "https://helloworldfromprodfuncapp.azurewebsites.net/api", ... }
```

The dev environment has **no** configuration override file (dev is the source of truth; prod gets `configuration.prod-006.yaml`).

### 3.6 Team scoping / merge

`artifacts.dev-006.api-team-00{1,2}/` are subset copies; `mergeArtifacts.ps1` / `mergeAllArtifacts.ps1` recombine them (`artifacts.dev-005.merged/`).

---

## 4. Workflows (triggers, auth, environments)

### 4.1 Infra: `.github/workflows/deploy-apim-basicv2.yml` (494 lines)

* Triggers: `workflow_dispatch` + `workflow_call` with inputs `instance_number` (default `006`), `location` (default `canadacentral`), `deploy_dev`, `deploy_prod`, `teardown_dev`, `teardown_prod`, `seed_demo_data` (lines 3-63).
* Auth: **OIDC** — `permissions: id-token: write` (lines 65-67); `azure/login@v2` with `client-id: ${{ secrets.APIM_AZURE_CLIENT_ID }}`, `tenant-id: ${{ secrets.APIM_AZURE_TENANT_ID }}`, `subscription-id: ${{ secrets.APIM_AZURE_SUBSCRIPTION_ID }}` (lines 94-98).
* Env vars: `TEMPLATE_FILE: infra/api-management-basicv2/main.bicep`, `PARAMETERS_DIR`, `RG_DEV: rg-apim-basicv2-dev-<n>`, `RG_PROD: rg-apim-basicv2-prod-<n>` (lines 69-75).
* Jobs: `validate` (`az bicep build`) -> `validate-dev`/`validate-prod` (`az deployment group validate`) -> `deploy-dev`/`deploy-prod` (what-if then create with 5-attempt retry + soft-deleted APIM purge via `deletedservices` REST, lines 164-200) -> optional AAD IdP config (line 393), seed (line 414) -> `teardown-dev`/`teardown-prod` (lines 438-486).
* GitHub environments: `APIM_BasicV2_Dev`, `APIM_BasicV2_Prod`, `APIM_BasicV2_Dev_Teardown`, `APIM_BasicV2_Prod_Teardown` (lines 91, 114, 290, 443, 472).

### 4.2 APIOps extractor: `.github/workflows/run-extractor-006.yaml`

* Trigger: `workflow_dispatch` with choice inputs `CONFIGURATION_YAML_PATH` (Extract All APIs | config files), `API_SPECIFICATION_FORMAT` (OpenAPIV3Yaml default first), `API_MANAGEMENT_SERVICE_OUTPUT_FOLDER_PATH` (default `artifacts.dev-006`) (lines 3-34).
* Environment: `dev-006` (line 47).
* Auth: **client secret, not OIDC** — env `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` from `secrets.*`; `AZURE_RESOURCE_GROUP_NAME`, `API_MANAGEMENT_SERVICE_NAME` from environment `vars.*` (lines 53-61).
* Post steps: Spectral lint of `apis/**/specification.{json,yaml,yml}` (non-blocking, lines 145-154), upload artifact, `peter-evans/create-pull-request@v6` using `secrets.PAT_TOKEN` onto branch `artifacts-from-portal-<run_id>` (lines 162-172).

### 4.3 APIOps publisher: `run-publisher-006.yaml` + reusable `run-publisher-with-env-006.yaml`

* Trigger: `pull_request` `closed` on `main` with `paths` = `artifacts.dev-006/**`, team folders, `configuration.prod-006.yaml` (lines 3-11); plus `workflow_dispatch` with `COMMIT_ID_CHOICE` (`publish-artifacts-in-last-commit` | `publish-all-artifacts-in-repo`) and folder choice (lines 13-32).
* Flow: `get-commit` -> dev publish (`API_MANAGEMENT_ENVIRONMENT: dev-006`, no config yaml) -> prod publish (`prod-006`, `CONFIGURATION_YAML_PATH: configuration.prod-006.yaml`) (lines 45-83). Same artifact folder is published to both; only overrides differ.
* Reusable workflow: `environment: ${{ inputs.API_MANAGEMENT_ENVIRONMENT }}` (line 26), `fetch-depth: 2` (for COMMIT_ID diffing), optional `cschleiden/replace-tokens@v1.3` with `{#`/`#}` tokens (lines 34-44 — note its `if` checks `== 'prod'`, so it never fires for `prod-006`), 4 publisher variants by config/commit presence, same client-secret env block (lines 48-56).
* GitHub environments for APIOps: `dev-006`, `prod-006` (README "APIops" table: secrets `AZURE_CLIENT_ID/SECRET/TENANT_ID/SUBSCRIPTION_ID`, vars `AZURE_RESOURCE_GROUP_NAME`, `API_MANAGEMENT_SERVICE_NAME`).
* ADO equivalents exist: `.azuredevops/apiops/run-extractor-006.yml`, `run-publisher-006.yml`, `.azuredevops/infra/deploy-apim-basicv2.yml`.

---

## 5. GenAI / OpenAI scenario

**None exists in this repo.** No Azure OpenAI backends, no `authentication-managed-identity resource="https://cognitiveservices.azure.com"`, no backend pools / circuit breakers, no `llm-token-limit` / `llm-emit-token-metric` / `azure-openai-*` policies, no chargeback workbooks/KQL. The upstream `Azure/apim-landing-zone-accelerator` has a `scenarios/workload-genai` tree, but this fork did not bring it in (not verified in this session — see follow-ups).

Implication: the AIGovernanceOffering repo's AI-gateway assets (`policies/demo1-token-limit.xml` `llm-token-limit`, `demo2-emit-token-metric.xml` `llm-emit-token-metric namespace="module8"`, `demo3-content-safety.xml`, `demo4-resilient-pool.xml` backend `demo4-aoai-pool` + MI to cognitiveservices) would be **net-new** to the LZA repo, so there is no naming collision to avoid, only format conventions to match.

---

## Compatibility recommendations (for the new AIGovernanceOffering APIM Basic v2 Bicep)

Naming / Bicep

1. Mirror the BasicV2 template contract: params `publisherEmail`, `publisherName`, `sku` (`@allowed(['BasicV2','StandardV2'])`, default `BasicV2`), `skuCount`, `location`, `environmentName` (`dev|qa|prod`), `instanceNumber`, `publisherPrincipalId`. Keep outputs `apiManagementName`, `apiManagementGatewayUrl`, `applicationInsightsName`, `keyVaultName` (if KV used), `resourceGroupName`.
2. Use the same name derivation: `apim-${environmentName}-${instanceNumber}-${uniqueString(resourceGroup().id)}`, `appi-<base>`, `log-<base>`, `kv-<base>` truncated to 24; RG `rg-apim-<variant>-<env>-<instance>` (e.g. `rg-apim-aigov-dev-001` or reuse `basicv2`). Pick a distinct `instanceNumber` (not `005`/`006`) to avoid collisions.
3. Use `Microsoft.ApiManagement/service@2024-06-01-preview` (same as LZA; also supports `llm-*` policies, backend pools with circuit breakers) and `identity: SystemAssigned`, TLS `customProperties`, `minApiVersion: '2019-12-01'`.
4. Keep the same logger contract: logger name `apimlogger` (`loggerType: applicationInsights`, `credentials.instrumentationKey: '{{instrumentationKey}}'`) + secret named value `instrumentationKey` created in Bicep. Leave diagnostics (`applicationinsights`, `azuremonitor`) and everything API-level out of Bicep — that is the LZA split. If you must set diagnostics now, express them as APIOps `diagnostics/applicationinsights/diagnosticInformation.json`.
5. Grant the APIM MI roles in Bicep (e.g. **Cognitive Services OpenAI User** on the AOAI account, matching the `authentication-managed-identity` usage) the same way LZA grants KV Secrets User; keep optional `publisherPrincipalId` -> **API Management Service Contributor** so APIOps can publish later.
6. Parameter files: LZA uses ARM JSON `main.parameters.<env>-<instance>.json` under the template folder. Prefer the same (or be ready to convert `.bicepparam`).

Folder structure / artifact formats

1. Put API-level config in an **APIOps v6-shaped folder** now, e.g. `apim/artifacts/` (root name is free; LZA uses `artifacts.<env>-<instance>`). Exact subfolder names matter and include spaces: `apis/`, `backends/`, `diagnostics/`, `loggers/`, `named values/`, `policy fragments/`, `products/`, `subscriptions/`, `tags/`, `version sets/`.
2. Policies: `apis/<apiName>/policy.xml` (API scope), `apis/<apiName>/operations/<opName>/policy.xml` (op scope), `products/<product>/policy.xml`, root `policy.xml` (global). Fragments as `policy fragments/<name>/policy.xml` with `<fragment>` root + `policyFragmentInformation.json`. The current `policies/demoN-*.xml` files can be moved/copied to `apis/<api>/policy.xml` with no content change.
3. API metadata: `apis/<apiName>/apiInformation.json` (`{"properties": {...}}` ARM properties shape) + `specification.yaml` in **OpenAPI v3 YAML**.
4. Backends: `backends/<name>/backendInformation.json` with `{"properties": {"url": ..., "protocol": "http", ...}}`. For AOAI pools use the same file with `"type": "Pool"` and `pool.services[].id` + `circuitBreaker` (verify exact extractor output shape — see follow-ups). Keep backend IDs stable and referenced via `set-backend-service backend-id="..."`.
5. Named values: `named values/<name>/namedValueInformation.json` (`displayName`, `secret`, `value` only when non-secret, `tags`). Put per-environment values (TPM limits, content-safety thresholds, AOAI endpoints) in `configuration.<env>.yaml` `namedValues:` overrides rather than hardcoding in Bicep. Prefer Key Vault-backed named values for secrets.
6. Products/subscriptions: `products/<p>/productInformation.json`, `products/<p>/apis/<api>/productApiInformation.json` (`{}`), `subscriptions/<s>/subscriptionInformation.json` with `scope: "/products/<p>"`. Use products (or subscriptions) as the chargeback unit so `llm-emit-token-metric` dimension `Subscription ID` / `Product ID` lines up.
7. Environment overrides at repo root as `configuration.<env>[-<instance>].yaml` with `apimServiceName`, `namedValues`, `backends`, `loggers`, `diagnostics`, `apis`, `products`, `policyFragments` lists of `{name, properties}`; secrets as `{#token#}`.
8. Naming for artifact ids: lowercase-kebab (`backend-weather-api`, `echo-api`), which is also what the demo policies already use (`demo4-aoai-pool`). Avoid names that collide with LZA's existing ones (`apimlogger` is intentionally shared; `starter`, `unlimited`, `echo-api`, `weatherapi` are taken).

Workflows (if/when added)

1. Infra: OIDC via `azure/login@v2` with secrets named `APIM_AZURE_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID` and environments `APIM_<Variant>_Dev|Prod`. Keep `workflow_dispatch` + `workflow_call` so a future LZA orchestrator (`create-lab.yml`) can call it.
2. APIOps: pin the same `apiops_release_version: v6.0.2`, env vars `API_MANAGEMENT_SERVICE_NAME`, `AZURE_RESOURCE_GROUP_NAME`, `API_MANAGEMENT_SERVICE_OUTPUT_FOLDER_PATH`, `CONFIGURATION_YAML_PATH`, `COMMIT_ID`. The LZA uses client secrets for APIOps; the APIOps binaries use `DefaultAzureCredential`-style env auth, so an OIDC `azure/login` before the run is a cleaner option — worth adopting in the new repo and upstreaming later.

Things to avoid copying

* `loggers/apimlogger/loggerInformation.json` in `artifacts.dev-006` has a stale `resourceId` (dev-005 AI). Don't extract/commit the logger if Bicep owns it, or override `resourceId` per env.
* `run-publisher-with-env-006.yaml` token replacement `if` checks `== 'prod'` and never runs for `prod-006`.
* Root-level `fed-cred.json`, `fed-cred-dev.json`, `.env.local` are committed in the LZA repo — keep such files out of the new repo.

---

## References (all paths relative to sibling repo root)

* `README.md` lines 1-160
* `infra/api-management-basicv2/main.bicep` lines 3-204
* `infra/api-management-basicv2/main.parameters.dev-006.json`
* `infra/api-management-create-with-external-vnet-publicip-stv2/main.bicep` lines 10-14, 414-436, 487-509, 564-649
* `reference-implementations/AppGW-IAPIM-Func/bicep/apim/apim.bicep` lines 23, 56, 73, 136
* `.github/workflows/deploy-apim-basicv2.yml` lines 3-200, 264, 290, 393-486
* `.github/workflows/run-extractor-006.yaml` lines 1-172
* `.github/workflows/run-publisher-006.yaml` lines 1-83
* `.github/workflows/run-publisher-with-env-006.yaml` lines 1-228
* `configuration.extractor.dev-006.yaml` lines 4-68
* `configuration.prod-006.yaml` lines 1-137
* `configuration.prod-005.yaml` lines 63-94
* `artifacts.dev-006/` (policy.xml, apis/weatherapi, backends/backend-weather-api, loggers/, diagnostics/, named values/, products/starter, subscriptions/demo-sub-starter)
* `artifacts.prod-006/policy fragments/SampleEmptyPolicyFragment/`
* External: [Azure/apiops](https://github.com/Azure/apiops), [Azure/apim-landing-zone-accelerator](https://github.com/Azure/apim-landing-zone-accelerator)

## Follow-up research (not done)

* Verify upstream `Azure/apim-landing-zone-accelerator` `scenarios/workload-genai` layout (backend pool Bicep, `emit-token-metric` dimensions, chargeback workbook/KQL) in case the LZA fork later pulls it in.
* Confirm the exact APIOps v6 extractor JSON shape for a `Pool`-type backend with `circuitBreaker` rules (extract from a test instance).
* Confirm APIOps v6 supports OIDC via workload identity env vars (`AZURE_FEDERATED_TOKEN_FILE`) or requires `azure/login` + Azure CLI credential fallback.

## Clarifying questions

* Should the new repo's artifact root be named `artifacts.<env>-<instance>` (LZA convention) or a neutral `apim/artifacts`?
* Which `instanceNumber` should the AIGovernanceOffering APIM use to avoid clashing with LZA `005`/`006`?
