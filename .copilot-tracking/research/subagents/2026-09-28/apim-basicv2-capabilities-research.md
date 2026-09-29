<!-- markdownlint-disable-file -->

> Historical research snapshot, superseded on 2026-09-28. Policy eligibility is not end-to-end verification. Revalidate model lifecycle, subscription eligibility, residency, capacity, pricing, diagnostics, and deletion behavior before deployment; do not adopt the defaults or unconditional sufficiency claims below. The authoritative design is .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. Original content is retained as evidence, not current implementation guidance; historical line references predate this notice.

# APIM Basic v2 capabilities for the AI governance lab set

Status: Complete (research only, no workspace code modified)
Date: 2026-09-28

## Research questions

1. Per-tier availability of `llm-token-limit` / `azure-openai-token-limit`, `llm-emit-token-metric` / `azure-openai-emit-token-metric`, `llm-content-safety`, backends (load-balanced pool + circuit breaker), `set-backend-service`, `retry`, `return-response`.
2. Basic v2 vs Standard v2 limits: SLA, scale units, requests, VNet, custom metrics, workspaces, self-hosted gateway, developer portal, API/backend limits, pricing, Canada region availability, provisioning time, soft-delete/purge.
3. Custom metrics prerequisites (App Insights logger, diagnostic `metrics: true`, Bicep), chargeback KQL, Azure-Samples/AI-Gateway lab modules and default SKU.
4. Latest API versions and role IDs.
5. Model availability in Canada East / Canada Central / East US for `gpt-4o-mini` / `gpt-4.1-mini` GlobalStandard; cost minimization.
6. Visualization options (workbook, dashboard, APIM Analytics "Language models").

## Verdict

**Basic v2 is sufficient for all four labs** (token limits, token metrics/chargeback, content safety, resilient backend pool + mock origin) with managed-identity auth to Azure OpenAI / Foundry and Content Safety.

Caveats:

* No VNet integration and no inbound private endpoint on Basic v2. All backends (Azure OpenAI/Foundry, Content Safety) must allow public network access. If a lab later needs private backends, move to Standard v2.
* No self-hosted gateway, no backup/restore, no multi-region, no static IP on any v2 tier (Basic v2 included).
* 10M API requests/month included; overage $3 per 1M. Irrelevant for a lab.
* Basic v2 is positioned by Microsoft as "development and testing scenarios, with SLA" (99.95%).
* v2 tiers use a token-bucket algorithm for `llm-token-limit`; if the same `counter-key` is used at multiple scopes, keep `tokens-per-minute` identical at every scope.
* Custom metric limits: max 5 custom dimensions per policy, 100 unique values per dimension, 1,000 active time series per namespace; excess is silently dropped. Design chargeback dimensions accordingly (for example Subscription ID + API ID + team header, not client IP).
* v2 gateway buffered payload limit is 2 MiB (vs 500 MiB classic); content safety evaluates up to 10,000 chars per prompt window and returns 403 if the Content Safety character limit is exceeded.
* **Canada Central does NOT offer `gpt-4o-mini` or `gpt-4.1-mini` as GlobalStandard (or regional Standard)**. Use Canada East or East US for the model accounts. APIM Basic v2 itself is available in both Canada Central and Canada East.
* **Role ID correction:** Cognitive Services User is `a97b65f3-24c7-4388-baec-2e87135dc908`, not `...-2e87a39b9ea9`.

## 1. Policy x tier support

The `azure-openai-token-limit-policy` and `azure-openai-emit-token-metric-policy` URLs now resolve to the `llm-*` pages (same content), so availability is identical. The AI-Gateway labs still use the `azure-openai-emit-token-metric` element name successfully.

| Policy / feature | APPLIES TO banner | Gateways line | Basic v2 | Consumption | URL |
|---|---|---|---|---|---|
| `llm-token-limit` (= `azure-openai-token-limit`) | Developer, Basic, Basic v2, Standard, Standard v2, Premium, Premium v2 | classic, v2, self-hosted, workspace | Yes | **No** | https://learn.microsoft.com/azure/api-management/llm-token-limit-policy |
| `llm-emit-token-metric` (= `azure-openai-emit-token-metric`) | All API Management tiers | classic, v2, consumption, self-hosted, workspace | Yes | Yes | https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy |
| `llm-content-safety` | Developer, Basic, Basic v2, Standard, Standard v2, Premium, Premium v2 | classic, v2, consumption, self-hosted, workspace | Yes | Gateway listed, tier not in banner | https://learn.microsoft.com/azure/api-management/llm-content-safety-policy |
| Backends: load-balanced pool | All API Management tiers | n/a (backend entity) | Yes (up to 30 backends per pool; round-robin, weighted, priority, session affinity) | Yes | https://learn.microsoft.com/azure/api-management/backends |
| Backends: circuit breaker | All tiers **except Consumption** | n/a | Yes (one rule per backend; `acceptRetryAfter`) | **No** | https://learn.microsoft.com/azure/api-management/backends#circuit-breaker |
| Backends: managed identity credentials | All tiers | n/a | Yes (`credentials.managedIdentity.resource = https://cognitiveservices.azure.com`) | Yes | https://learn.microsoft.com/azure/api-management/backends#configure-managed-identity-for-authorization-credentials |
| `set-backend-service` | All API Management tiers | classic, v2, consumption, self-hosted, workspace | Yes | Yes | https://learn.microsoft.com/azure/api-management/set-backend-service-policy |
| `retry` | All API Management tiers | classic, v2, consumption, self-hosted, workspace | Yes (count 1–50, `first-fast-retry`) | Yes | https://learn.microsoft.com/azure/api-management/retry-policy |
| `return-response` (mock origin) | All API Management tiers | classic, v2, consumption, self-hosted, workspace | Yes | Yes | https://learn.microsoft.com/azure/api-management/return-response-policy |

Key usage notes:

* `llm-token-limit`: sections inbound; scopes global/workspace/product/API/operation. 429 when TPM exceeded, 403 when quota exceeded. `token-quota-period`: Hourly/Daily/Weekly/Monthly/Yearly. Counter is per gateway (not aggregated across regions).
* `llm-emit-token-metric`: inbound only; default namespace "API Management"; default dimensions usable without `value`: API ID, Operation ID, Product ID, User ID, Subscription ID, Location, Gateway ID, Backend ID. For streaming, send `stream_options.include_usage=true`.
* `llm-content-safety`: inbound and/or outbound; scopes global/workspace/product/API (not operation). Prereqs: Content Safety resource; APIM MI has **Cognitive Services User** on it; backend URL `https://<name>.cognitiveservices.azure.com`; backend credential MI with resource `https://cognitiveservices.azure.com`. Categories Hate/SelfHarm/Sexual/Violence, thresholds 0–7, `shield-prompt`, blocklists. Blocked = 403 (streaming: stream stops, no 403).
* Circuit breaker caution from Learn: Azure OpenAI 429s can carry large `Retry-After`; configure rules for 429 and `acceptRetryAfter`.

## 2. Basic v2 vs Standard v2

Sources: https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview, https://learn.microsoft.com/azure/api-management/api-management-features, https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits#limits---api-management-classic-and-v2-tiers, https://azure.microsoft.com/pricing/details/api-management/, https://learn.microsoft.com/azure/api-management/api-management-region-availability

| Item | Basic v2 | Standard v2 |
|---|---|---|
| Positioning | Dev/test, with SLA | Production, network-isolated backends |
| SLA | 99.95% | 99.95% |
| Max scale units | 10 | 10 |
| Price (USD list, pricing page default) | $150.01/month per unit | $700/month (+$500 per extra unit) |
| Included requests | 10M/month, then $3 per 1M | 50M/month, then $2.50 per 1M |
| Built-in cache | 250 MB | 1 GB |
| VNet integration (outbound to VNet backends) | **No** | Yes |
| Inbound private endpoint | **No** | Yes |
| VNet injection | No | No (Premium/Premium v2 only) |
| Workspaces | Yes (feature table) | Yes |
| Self-hosted gateway | No | No |
| Developer portal | Yes (30 pages/widgets limit) | Yes (50) |
| Azure Monitor metrics, Log Analytics request logs, App Insights request logs | Yes | Yes |
| API operations limit | 10,000 | 50,000 |
| Products / subscriptions | 200 / 15,000 | 500 / 25,000 |
| Loggers | 100 | 200 |
| Backends per pool | 30 | 30 |
| Canada Central / Canada East availability | Yes / Yes | Yes / Yes |
| Min API version for v2 features | 2024-05-01 | 2024-05-01 |

Other v2 facts:

* Deployment "in minutes"; fast scaling (v2 overview). No specific minute count is published; classic tiers typically take 30–45+ min.
* v2 runtime limits: buffered payload 2 MiB, request URL 16,384 bytes, policy document 512 KiB.
* v2 unavailable: multi-region, Event Grid, Git config, DDoS Protection, backup/restore, upgrade from classic, resource move, self-hosted gateway, free managed TLS cert, cipher config.
* Pricing page also shows an "API Management (AI Gateway tier)" section marked "Pricing details are coming soon".
* CAD price is not published on the page fetch; at roughly 1.37 USD→CAD, Basic v2 ≈ CAD 205/month (estimate, verify in Pricing Calculator with Canada Central/CAD).

### Soft delete / purge (APIM)

Source: https://learn.microsoft.com/azure/api-management/soft-delete

* Deleting with API version 2020-06-01-preview or later (portal, CLI, `az group delete`) soft-deletes the instance for **48 hours**.
* While soft-deleted, the **name cannot be reused**. Redeploying the same name fails until purged or recovered.
* Purge: `az apim deletedservice purge --location <region> --service-name <name>`; list with `az apim deletedservice list`.
* Purge needs subscription-scope permissions `Microsoft.ApiManagement/locations/deletedservices/delete` and `Microsoft.ApiManagement/deletedservices/read` (plus Contributor on the instance).
* Recover: PUT service with `properties.restore = true`.
* A purged name cannot be reused in a **different subscription** for several days (dangling DNS protection).

## 3. Custom metrics for chargeback

Sources: https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights#emit-custom-metrics, https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy

Required configuration:

1. App Insights: enable **Custom metrics (Preview) → With dimensions** (portal: Usage and estimated costs). IaC: `Microsoft.Insights/components` property `CustomMetricsOptedInType: 'WithDimensions'` (not in Bicep types, BCP037 warning, but works; used by AI-Gateway `modules/monitor/v1/appinsights.bicep`).
2. APIM logger `Microsoft.ApiManagement/service/loggers` with `loggerType: 'applicationInsights'`. Recommended: `credentials.connectionString` + `credentials.identityClientId: 'SystemAssigned'` and grant APIM MI **Monitoring Metrics Publisher** on the App Insights resource. (Instrumentation-key-only loggers are rejected if App Insights has `DisableLocalAuth: true`.)
3. Diagnostic `applicationinsights` (global `service/diagnostics` or per-API `service/apis/diagnostics`) with `loggerId` and **`metrics: true`**. Learn says "currently you must add this property by using the REST API", but Bicep works: AI-Gateway `modules/apim/v2/inference-api.bicep` uses `Microsoft.ApiManagement/service/apis/diagnostics@2022-08-01` named `applicationinsights` with `metrics: true`.
4. Policy at a scope where that diagnostic applies.

Bicep sketch (derived from Learn + AI-Gateway module):

```bicep
resource logger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appInsights.id
    credentials: {
      connectionString: appInsights.properties.ConnectionString
      identityClientId: 'SystemAssigned'
    }
  }
}

resource apiDiag 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = {
  parent: api
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    metrics: true
    alwaysLog: 'allErrors'
    httpCorrelationProtocol: 'W3C'
    sampling: { samplingType: 'fixed', percentage: 100 }
  }
}
```

AI-Gateway `labs/token-metrics-emitting/policy.xml` (namespace `openai`) dimensions: `Subscription ID` = `context.Subscription.Id`, `Client IP`, `API ID`, `User ID` from header `x-user-id`. For team chargeback, replace Client IP with a team dimension (e.g., `x-team` header or `context.Product.Id`).

Chargeback KQL (App Insights `customMetrics`; for workspace-based App Insights query the Log Analytics `AppMetrics` table where `Name`, `Sum`, `Properties` replace `name`, `valueSum`, `customDimensions`). Metric names "Prompt Tokens", "Completion Tokens", "Total Tokens" are the documented token metrics (verify names against emitted data in the lab):

```kusto
customMetrics
| where timestamp > ago(30d)
| where name in ("Prompt Tokens", "Completion Tokens", "Total Tokens")
| extend subscriptionId = tostring(customDimensions["Subscription ID"]),
         team = tostring(customDimensions["Team"])
| summarize tokens = sum(valueSum) by name, subscriptionId, team, bin(timestamp, 1d)
```

Cost = tokens × model rate (e.g., gpt-4.1-mini Global $0.40/1M input, $1.60/1M output).

Alternative chargeback source (no custom metrics): diagnostic setting category **"Logs related to generative AI gateway"** → Log Analytics table `ApiManagementGatewayLlmLog` (token usage, model), join to `ApiManagementGatewayLogs` on `CorrelationId` for `ApimSubscriptionId`. Learn explicitly lists "Calculate usage for billing" as a scenario. https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs

### Azure-Samples/AI-Gateway references

Repo: https://github.com/Azure-Samples/AI-Gateway (labs at `labs/`)

| Lab | Path | Notes |
|---|---|---|
| Token rate limiting | `labs/token-rate-limiting` | `llm-token-limit` |
| Token metrics emitting | `labs/token-metrics-emitting/main.bicep`, `policy.xml` | Uses `modules/operational-insights/v1/workspaces.bicep`, `modules/monitor/v1/appinsights.bicep` (`customMetricsOptedInType: 'WithDimensions'`), `modules/apim/v2/apim.bicep`, `modules/cognitive-services/v3/foundry.bicep`, `modules/apim/v2/inference-api.bicep` (passes `apimLoggerId`, `appInsightsId`, `appInsightsInstrumentationKey`) |
| Content safety | `labs/content-safety/main.bicep` | `Microsoft.CognitiveServices/accounts@2024-04-01-preview`, kind `ContentSafety`, sku `S0`, `customSubDomainName`; `raiBlocklists@2025-06-01`; role `a97b65f3-24c7-4388-baec-2e87135dc908` (Cognitive Services User) to APIM MI; backend `content-safety-backend` with `credentials.managedIdentity.resource: 'https://cognitiveservices.azure.com'`; `configureCircuitBreaker: true` |
| Backend pool load balancing | `labs/backend-pool-load-balancing` (also `-tf`) | Pool created by `inference-api.bicep` when >1 AI service |
| Built-in logging | `labs/built-in-logging` | LLM logs to Azure Monitor (`largeLanguageModel.logs: 'enabled'` in `azuremonitor` diagnostic) |
| FinOps framework | `labs/finops-framework` (`main.bicep`, `dashboard.bicep`, `workbooks/`, `products-policy.xml`) | Token limit per product + Azure Monitor alerts + Logic App to disable subscriptions over cost quota |

Module details:

* `modules/apim/v2/apim.bicep`: `Microsoft.ApiManagement/service@2024-06-01-preview`, `param apimSku string = 'Basicv2'` (allowed Consumption, Developer, Basic, Basicv2, Standard, Standardv2, Premium), capacity 1, `SystemAssigned` identity, `releaseChannel` param (Early/Default/Late/GenAI); App Insights logger `loggers@2021-12-01-preview` with instrumentation key; `azuremonitor` logger + `diagnosticSettings` (`AllLogs`, `AllMetrics`, Dedicated tables).
* `modules/apim/v2/inference-api.bicep`: backends `@2024-06-01-preview`; circuit breaker rule `count: 1`, `interval: 'PT1M'`, `statusCodeRanges 429–429`, `tripDuration: 'PT1M'`, `acceptRetryAfter: true`; pool `type: 'Pool'` with `services[].id: '/backends/<name>'`, `priority`, `weight`; API `subscriptionKeyParameterNames.header: 'api-key'`.
* `modules/cognitive-services/v3/foundry.bicep`: `Microsoft.CognitiveServices/accounts@2025-06-01`, kind `AIServices`, sku `S0`, `allowProjectManagement: true`, `disableLocalAuth: false`, projects `@2025-04-01-preview`; assigns Cognitive Services User to APIM MI.

## 4. API versions and role IDs

| Resource | Latest GA | Latest preview | Used by AI-Gateway | Recommendation |
|---|---|---|---|---|
| `Microsoft.ApiManagement/service` (+ backends, loggers, diagnostics, apis, policies) | **2024-05-01** | 2025-09-01-preview (also 2025-03-01-preview, 2024-10-01-preview, 2024-06-01-preview) | 2024-06-01-preview | `2024-05-01` (GA, v2 features supported); use `2024-06-01-preview` only if needed for LLM diagnostic `largeLanguageModel` block |
| `Microsoft.CognitiveServices/accounts` (+ `/deployments`) | **2026-07-01** (also 2026-05-01, 2026-03-01, 2025-12-01, 2025-09-01, 2025-06-01, 2024-10-01) | 2026-07-15-preview | 2025-06-01 | `2025-06-01` or newer GA; `2024-10-01` also valid |
| `Microsoft.Insights/components` | 2020-02-02 | — | 2020-02-02 | 2020-02-02 |

Sources: https://learn.microsoft.com/azure/templates/microsoft.apimanagement/service, https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts

Content Safety: `kind: 'ContentSafety'`, `sku.name: 'S0'` (or `F0` free, 5,000 text records/month, one free per subscription per type), requires `customSubDomainName` for Entra/MI auth.

Role IDs (verified at https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning):

| Role | ID | Use |
|---|---|---|
| Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` | Least privilege for APIM MI → Azure OpenAI/Foundry inference |
| Cognitive Services User | **`a97b65f3-24c7-4388-baec-2e87135dc908`** | Required by Learn for APIM MI → Content Safety; also what AI-Gateway assigns for Foundry |
| Monitoring Metrics Publisher | `3913510d-42f4-4e42-8a64-420c390055eb` | APIM MI → App Insights when logger uses MI credentials (ID from prior verified work; Learn page names the role) |

## 5. Model availability and cost

Source: https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability

| Model (version) | Deployment | canadacentral | canadaeast | eastus |
|---|---|---|---|---|
| gpt-4o-mini (2024-07-18) | Global Standard | **No** | Yes | Yes |
| gpt-4.1-mini (2025-04-14) | Global Standard | **No** | Yes | Yes |
| gpt-4.1-nano (2025-04-14) | Global Standard | **No** | Yes | Yes |
| gpt-4o-mini | Standard (regional) | No | No | Yes |
| gpt-4.1-mini | Standard (regional) | No | Yes | Yes |
| gpt-4o-mini / gpt-4.1-mini | Data Zone Standard (US) | n/a | n/a | Yes |

Pricing (USD per 1M tokens, https://azure.microsoft.com/pricing/details/azure-openai/):

| Model | Global input / output | Data Zone / Regional input / output |
|---|---|---|
| gpt-4.1-nano | $0.10 / $0.40 | $0.11 / $0.44 |
| gpt-4o-mini | $0.15 / $0.60 | $0.165 / $0.66 |
| gpt-4.1-mini | $0.40 / $1.60 | $0.44 / $1.76 |

Cost-minimizing choice: GlobalStandard `gpt-4.1-nano` or `gpt-4o-mini` (cheapest with broad availability). For the backend-pool lab, deploy the same model in two accounts (Canada East priority 1, East US priority 2), each with small capacity (e.g., 1–10K TPM). Quota per subscription/region was not queried; check with `az cognitiveservices usage list -l canadaeast`.

Content Safety: Standard $0.38 per 1,000 text records (1 record ≤ 1,000 chars); Free 5,000 records/month. https://azure.microsoft.com/pricing/details/cognitive-services/content-safety/

### Estimated monthly cost of the minimal lab stack (USD list)

| Component | Assumption | Monthly if left running | Per lab day |
|---|---|---|---|
| APIM Basic v2 | 1 unit, 730 h | ~$150 (~CAD 205) | ~$5 |
| Azure OpenAI/Foundry × 2 accounts | Pay-per-token, ~2M tokens total | < $2 | < $1 |
| Content Safety S0 (or F0) | < 10K text records | < $4 (F0: $0) | < $1 |
| App Insights + Log Analytics | < 1 GB ingestion (pay-as-you-go, first 5 GB/month per billing account free for Log Analytics — verify) | ~$0–5 | ~$0 |
| **Total** |  | **~$155–160** | **~$5–7** |

Recommendation: deploy per session and tear down (APIM Basic v2 provisions in minutes), rather than leaving it running.

## 6. Visualization

* **APIM Analytics (Azure Monitor-based dashboard)**: Monitoring → Analytics, **"Language models" tab** shows token consumption and requests for LLM APIs. Needs diagnostic setting to Log Analytics with "Logs related to ApiManagement Gateway" + "Logs related to generative AI gateway", resource-specific tables. Available in v2 tiers (legacy built-in analytics is classic-only and retires March 2027). https://learn.microsoft.com/azure/api-management/monitor-api-management#get-api-analytics-in-azure-api-management and https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs
* **Azure Monitor Workbook**: AI-Gateway `modules/monitor/v1/appinsights.bicep` supports `Microsoft.Insights/workbooks@2022-04-01` (`useWorkbook`, `workbookJson`, category `UsageAnalysis`); `labs/finops-framework/workbooks/` and `dashboard.bicep` provide ready-made chargeback workbook/dashboard.
* **Metrics Explorer**: custom namespace (e.g., `openai`) → split by `Subscription ID` / team dimension; pin to Azure Dashboard.
* **Managed Grafana**: API Management dashboard 16604 (extra cost; optional).

## Teardown gotchas

1. **APIM soft delete (48 h)**: `az group delete` soft-deletes; redeploying the same name fails. Run `az apim deletedservice purge --location <region> --service-name <name>` (needs subscription-scope purge permissions). Or randomize names per deployment (`uniqueString` + timestamp).
2. **Cognitive Services / Foundry / Content Safety soft delete (48 h)**: same-name redeploy blocked for 48 h. Purge per Learn: `az resource delete --ids /subscriptions/<sub>/providers/Microsoft.CognitiveServices/locations/<loc>/resourceGroups/<rg>/deletedAccounts/<name>` (or `az cognitiveservices account purge -l <loc> -g <rg> -n <name>`). Purge requires `Microsoft.CognitiveServices/locations/resourceGroups/deletedAccounts/delete`; Contributor must be at **subscription** scope. The resource group must still exist to recover. https://learn.microsoft.com/azure/ai-services/recover-purge-resources
3. Delete model deployments before deleting the account if any provisioned deployment exists (charges continue until purge). Not applicable for GlobalStandard, but harmless.
4. Log Analytics workspaces also soft-delete (14 days, prior knowledge; not re-verified here); use `az monitor log-analytics workspace delete --force` to avoid name collision.
5. APIM name reuse across subscriptions is blocked for days even after purge.

## Recommended next research (not completed)

* [ ] Verify exact emitted metric names ("Total Tokens", "Prompt Tokens", "Completion Tokens") and whether cached/reasoning token metrics appear, by running the lab once.
* [ ] Confirm Azure AI Content Safety region availability in Canada East / Canada Central (not fetched).
* [ ] Confirm CAD pricing for Basic v2 in Canada Central via Pricing Calculator.
* [ ] Check subscription GlobalStandard TPM quota for gpt-4.1-nano / gpt-4o-mini in Canada East and East US.
* [ ] Read `labs/finops-framework/main.bicep` and `workbooks/` for reusable workbook JSON.
* [ ] Confirm whether `metrics: true` must be on the global `service/diagnostics/applicationinsights` or per-API diagnostic when policy is at global scope.

## Clarifying questions

* Must model inference stay in Canada (data residency)? If yes, Canada East GlobalStandard still processes globally; regional Standard in Canada East exists only for gpt-4.1-mini (not gpt-4o-mini).
* Should the App Insights resource use `DisableLocalAuth: true`? If yes, the APIM logger must use connection string + MI and the Monitoring Metrics Publisher role.
