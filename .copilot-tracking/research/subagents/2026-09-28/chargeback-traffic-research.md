<!-- markdownlint-disable-file -->

> Historical research snapshot, superseded on 2026-09-28. Do not execute or copy the accounting, traffic-budget, diagnostic, or workflow examples below. Correlation-only joins, claims of exact billing, unsupported privacy settings, and unguarded bursts were rejected by adversarial review. The authoritative design is .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. Original content is retained as evidence, not current implementation guidance; historical line references predate this notice.

# Chargeback Traffic Research (APIM AI Gateway + GitHub Actions)

Status: Complete (research only, no repo files modified except this doc)
Date: 2026-09-28

## Research Questions

1. How does Azure-Samples/AI-Gateway model teams/products/subscriptions for chargeback (finops-framework, token-metrics-emitting, built-in-logging)? Workbooks, dashboard Bicep, KQL, pricing, traffic generation.
2. Bicep for App Insights `CustomMetricsOptedInType: 'WithDimensions'`, APIM App Insights logger (connection string + MI), `applicationinsights` diagnostic with `metrics: true`, APIM diagnostic settings to Log Analytics (`GatewayLlmLogs`, `GatewayLogs`, `Dedicated`).
3. Bicep for `Microsoft.Insights/workbooks` with `serializedData`; chargeback KQL for `customMetrics` (namespace `module8`) and `ApiManagementGatewayLlmLog` ⨝ `ApiManagementGatewayLogs`.
4. APIM Bicep for per-team products + subscriptions; fetching keys in GitHub Actions via `listSecrets` with `::add-mask::`.
5. Traffic generator design (Python, per-team keys, `x-client-app`, random prompt sizes, cron, token budget, forced 429s). Cron limits.
6. Screenshot automation feasibility (portal vs. KQL → matplotlib).

## Local Repo Context

* `policies/demo2-emit-token-metric.xml` lines 18-22: `<llm-emit-token-metric namespace="module8">` with dimensions `API ID`, `Subscription ID` (default dims, no value) and `ClientApp` = `context.Request.Headers.GetValueOrDefault("x-client-app","unknown")`.
* `policies/demo1-token-limit.xml` lines 26-35: `llm-token-limit` with `counter-key = Subscription.Id + "-" + x-demo-run`, `tokens-per-minute="{{demo1-tokens-per-minute}}"`, `token-quota="{{demo1-daily-token-cap}}"`, `token-quota-period="Daily"`, headers `remaining-tokens`, `tokens-consumed`, `Retry-After`.
* `shared/apim.py` lines 657-705 (`query_token_metrics`) documents that `llm-emit-token-metric` namespace is only a label on App Insights `customMetrics`; it is NOT an Azure Monitor metric namespace on the APIM resource. Lines 730-760 (`query_app_insights_token_metrics`) query `customMetrics | where name in (...) | extend dimension_value = tostring(customDimensions['ClientApp'])`.
* `notebooks/demo2-token-metrics.ipynb` uses bounded `CLIENT_APP_ALLOW_LIST = {"claims-portal", "analyst-copilot"}` and sends the key as `Ocp-Apim-Subscription-Key` (demo1 line 415).

## 1. Azure-Samples/AI-Gateway findings

### Lab inventory (https://github.com/Azure-Samples/AI-Gateway/tree/main/labs)

Relevant labs: `finops-framework`, `token-metrics-emitting`, `built-in-logging`, `token-rate-limiting`, `ai-foundry-model-gateway`, `aigw-foundry-models`. Shared modules under `modules/` (`modules/apim/v2/apim.bicep`, `modules/apim/v2/inference-api.bicep`, `modules/monitor/v1/appinsights.bicep`, `modules/operational-insights/v1/workspaces.bicep`, `modules/cognitive-services/v3/foundry.bicep`).

### finops-framework (https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/finops-framework)

Files: `main.bicep`, `dashboard.bicep`, `policy.xml`, `products-policy.xml`, `workbooks/` (`alerts.json`, `azure-openai-insights.json`, `cost-analysis.json`), `finops-framework.ipynb`, `result.png`. Latest commit 1679e31 "correct 1000x overstated cost" (2 weeks before 2026-09-28) — pricing units matter (see below).

Chargeback data model (from `finops-framework.ipynb` cell 0):

* Products = tiers with quotas: `platinum` (tpm 2000, tokenQuota 1,000,000 Monthly, costQuota 0.015), `gold` (tpm 1000, costQuota 0.010), `silver` (tpm 500, costQuota 0.005).
* Subscriptions = consumers, each scoped to a product: `subscription1→platinum`, `subscription2→gold`, `subscription3/4→silver`.
* Models config carries retail meter SKU names for pricing lookup: `{"name":"gpt-4.1-mini", ..., "inputTokensMeterSku":"gpt 4.1 mini Inp glbl", "outputTokensMeterSku":"gpt 4.1 mini Outp glbl"}`.
* `apim_sku = 'Basicv2'` — confirms LLM logging + token metrics work on Basic v2.

Bicep patterns (`labs/finops-framework/main.bicep`):

* App Insights module called with `customMetricsOptedInType: 'WithDimensions'`.
* Per-product token limits generated into the API policy via `<choose><when condition='@((string)context.Product?.Id == "${p.name}")'><llm-token-limit counter-key="@(context.Subscription.Id)" tokens-per-minute="${p.tpm}" token-quota="${p.tokenQuota}" token-quota-period="${p.tokenQuotaPeriod}" .../></when>`.
* `Microsoft.ApiManagement/service/products@2024-06-01-preview` (`approvalRequired: true`, `subscriptionRequired: true`, `state: 'published'`), `products/apiLinks` linking the inference API, `products/policies`, `service/users`, `service/subscriptions` with `scope: '/products/${subscription.product}'`, `@batchSize(1)` on all loops.
* Output `apimSubscriptions` array with `apimSubscriptions[i].listSecrets().primaryKey` (with `#disable-next-line outputs-should-not-contain-secrets`) — NOT recommended for our CI (deployment outputs are readable by anyone with deployment read). Use `listSecrets` REST at runtime instead (section 4).
* Pricing: custom LA table `PRICING_CL` (`Microsoft.OperationalInsights/workspaces/tables@2023-09-01`, columns `TimeGenerated, Model, InputTokensPrice, OutputTokensPrice`) + Direct DCR `Microsoft.Insights/dataCollectionRules@2023-03-11` (`kind: 'Direct'`, stream `Custom-Json-PRICING_CL`, `transformKql: 'source'`). Same for `SUBSCRIPTION_QUOTA_CL (Subscription, CostQuota)`. Deployer granted Monitoring Metrics Publisher (`3913510d-42f4-4e42-8a64-420c390055eb`) on each DCR.
* Pricing loaded by notebook from Retail Prices API: `https://prices.azure.com/api/retail/prices?currencyCode='USD'&$filter=serviceName eq 'Foundry Models' and unitOfMeasure eq '1K' and armRegionName eq '<region>'`, matched on `skuName`, uploaded with `azure.monitor.ingestion.LogsIngestionClient.upload(rule_id, stream_name, logs)`. Notebook note: "retail price returned by the pricing API is already expressed per 1K tokens ... stored as-is. The cost queries divide the token count by 1000".
* Workbooks: `Microsoft.Insights/workbooks@2022-04-01`, `kind: 'shared'`, `name: guid(resourceGroup().id, resourceSuffix, 'costAnalysis')`, `serializedData: replace(loadTextContent('workbooks/cost-analysis.json'), '{workspace-id}', logAnalytics.id)`, `sourceId: logAnalytics.id`, `category: 'workbook'`. Also `string(loadJsonContent(...))` variant.
* Enforcement loop: `scheduledqueryrules@2025-01-01-preview` (evaluationFrequency PT5M, `overrideQueryTimeRange: 'P2D'`) → action group → Logic App (system MI, APIM Service Contributor `312a565d-c81f-4fd8-895a-4e21e48d571c`) PATCHes `.../subscriptions/{name}?api-version=2024-06-01-preview` with `state: suspended|active`.
* `dashboard.bicep` = portal dashboard pinning the workbooks + App Insights (params `workbookCostAnalysisId`, `workbookAzureOpenAIInsightsId`, `appInsightsId`).

`labs/finops-framework/policy.xml`: `<azure-openai-emit-token-metric namespace="aiusage"><dimension name="Product" value="@(context.Product.Id)" /></azure-openai-emit-token-metric>` plus the `{product-token-limits}` choose block.

Canonical cost KQL (`workbooks/cost-analysis.json`, query-0; same query in alert rules in `main.bicep`):

```kusto
let llmHeaderLogs = ApiManagementGatewayLlmLog
| where TimeGenerated >= startofmonth(now()) and TimeGenerated <= endofmonth(now())
| where DeploymentName != '';
let llmLogsWithSubscriptionId = llmHeaderLogs
| join kind=leftouter ApiManagementGatewayLogs on CorrelationId
| project SubscriptionName = ApimSubscriptionId, DeploymentName, PromptTokens, CompletionTokens, TotalTokens;
llmLogsWithSubscriptionId
| join kind=inner (PRICING_CL | summarize arg_max(TimeGenerated, *) by Model | project Model, InputTokensPrice, OutputTokensPrice)
    on $left.DeploymentName == $right.Model
| extend InputCost = PromptTokens * InputTokensPrice
| extend OutputCost = CompletionTokens * OutputTokensPrice
| summarize InputCost = sum(InputCost), OutputCost = sum(OutputCost) by SubscriptionName
| extend TotalCost = (InputCost + OutputCost) / 1000
| join kind=inner (SUBSCRIPTION_QUOTA_CL | summarize arg_max(TimeGenerated, *) by Subscription | project Subscription, CostQuota)
    on $left.SubscriptionName == $right.Subscription
| project SubscriptionName, CostQuota, TotalCost
```

Query-1 is the same, binned `by SubscriptionName, bin(TimeGenerated, 1m)` with `visualization: unstackedbar`. Key detail: `where DeploymentName != ''` keeps only the header row per request (LLM log rows are split by `SequenceNumber` for message content).

Traffic generation (notebook "Execute multiple runs"): `runs = 10`, `sleep_time_ms = 100`, each iteration `random.choice(apim_subscriptions)` + `random.choice(models_config)`, `AzureOpenAI(azure_endpoint=f"{gateway}/{inference_api_path}", api_key=key, api_version="2025-03-01-preview")`, `chat.completions.create(..., extra_headers={"x-user-id": "alex"})`. No budget/jitter logic — trivial loop.

### token-metrics-emitting (https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/token-metrics-emitting)

* `policy.xml`: `<azure-openai-emit-token-metric namespace="openai">` dims `Subscription ID`, `Client IP`, `API ID`, `User ID` (from `x-user-id` header, default `N/A`).
* Notebook traffic: 3 `AzureOpenAI` clients (one per subscription key), loops `runs` × 3.
* KQL (via `az monitor app-insights query --app <name> -g <rg>`):

```kusto
customMetrics
| where name == 'Total Tokens'
| extend parsedCustomDimensions = parse_json(customDimensions)
| extend clientIP = tostring(parsedCustomDimensions.['Client IP'])
| extend apiId = tostring(parsedCustomDimensions.['API ID'])
| extend apimSubscription = tostring(parsedCustomDimensions.['Subscription ID'])
| extend UserId = tostring(parsedCustomDimensions.['User ID'])
| project timestamp, value, clientIP, apiId, apimSubscription, UserId
```

* Results plotted with pandas + matplotlib (`df.plot(kind='line', x='timestamp', y='value')`) — precedent for the chart-rendering approach in section 6.
* Portal guidance: App Insights → Metrics → namespace → "Total Tokens" Sum → split by Subscription Id.

### built-in-logging (https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/built-in-logging)

Uses the built-in LLM logging (`largeLanguageModel` block on the `azuremonitor` API diagnostic) — prompts, completions, and tokens logged to `ApiManagementGatewayLlmLog`.

### Shared modules

`modules/monitor/v1/appinsights.bicep`:

```bicep
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: applicationInsightsLocation
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: lawId
    // BCP037: Not yet added to latest API: https://github.com/Azure/bicep-types-az/issues/2048
    #disable-next-line BCP037
    CustomMetricsOptedInType: customMetricsOptedInType   // @allowed WithDimensions|NoDimensions|NoMeasurements|Off
  }
}
```

`modules/apim/v2/apim.bicep`:

* `Microsoft.Insights/diagnosticSettings@2021-05-01-preview` scoped to APIM: `workspaceId: lawId`, `logAnalyticsDestinationType: 'Dedicated'`, `logs: [{ categoryGroup: 'AllLogs', enabled: true }]`, `metrics: [{ category: 'AllMetrics', enabled: true }]`.
* Logger `azuremonitor` (`loggerType: 'azureMonitor'`, `isBuffered: false`) — required for the API-level `azuremonitor` diagnostic that feeds `GatewayLogs`/`GatewayLlmLogs`.
* Logger `appinsights-logger` (`Microsoft.ApiManagement/service/loggers@2021-12-01-preview`, `loggerType: 'applicationInsights'`, `credentials: { instrumentationKey: ... }`, `resourceId: appInsightsId`, `isBuffered: false`) — ikey-based; we should use connection string + MI (section 2).

`modules/apim/v2/inference-api.bicep`:

* `apis/diagnostics@2024-06-01-preview` name `azuremonitor`: `loggerId: apimLoggerId`, `sampling fixed 100`, `verbosity: 'verbose'`, `logClientIp: true`, `alwaysLog: 'allErrors'`, frontend/backend headers `[]` body bytes 0, plus:

```bicep
largeLanguageModel: {
  logs: 'enabled'
  requests:  { messages: 'all', maxSizeInBytes: 262144 }
  responses: { messages: 'all', maxSizeInBytes: 262144 }
}
```

* `apis/diagnostics@2022-08-01` name `applicationinsights`: `loggerId: .../loggers/appinsights-logger`, `metrics: true`, `httpCorrelationProtocol: 'W3C'`, `verbosity: 'verbose'`, sampling 100, headers list `['Content-type','User-agent','x-ms-region','x-ratelimit-remaining-tokens','x-ratelimit-remaining-requests']`.
* API `subscriptionKeyParameterNames: { header: 'api-key', query: 'api-key' }` (so OpenAI SDK `api_key` works as the APIM key). Our labs use `Ocp-Apim-Subscription-Key`; either works if we set the param names accordingly.

## 2. Monitoring Bicep (docs-verified)

Sources:

* https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-app-insights (logger with connection string + MI; "Emit custom metrics": enable "Custom metrics (Preview) → With dimensions" and add `"metrics": true` to the `applicationinsights` diagnostic; logger must be at the scope where the metric policy runs).
* https://learn.microsoft.com/en-us/azure/api-management/llm-emit-token-metric-policy (prereqs; max 5 custom dimensions; APIM caps 100 unique values per dimension and 1,000 active time series per namespace — overflow silently discarded; default dim names usable without value: API ID, Operation ID, Product ID, User ID, Subscription ID, Location, Gateway ID, Backend ID; streaming needs `include_usage`).
* https://learn.microsoft.com/en-us/azure/api-management/monitor-api-management-reference (resource log categories: `GatewayLogs` → `ApiManagementGatewayLogs`, `GatewayLlmLogs` → `ApiManagementGatewayLlmLog`, `GatewayMCPLogs`, `WebSocketConnectionLogs`, `DeveloperPortalAuditLogs`).

MI requirement: grant APIM identity **Monitoring Metrics Publisher** (`3913510d-42f4-4e42-8a64-420c390055eb`) on the App Insights component. Mandatory if App Insights has `DisableLocalAuth: true` (otherwise ingestion is silently rejected — see user memory note on App Insights DisableLocalAuth).

```bicep
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    DisableLocalAuth: true
    #disable-next-line BCP037
    CustomMetricsOptedInType: 'WithDimensions'
  }
}

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  sku: { name: 'BasicV2', capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: { publisherEmail: publisherEmail, publisherName: publisherName }
}

resource appiMetricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appi
  name: guid(appi.id, apim.id, '3913510d-42f4-4e42-8a64-420c390055eb')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appiLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appi.id
    isBuffered: false
    credentials: {
      connectionString: appi.properties.ConnectionString
      identityClientId: 'SystemAssigned'
    }
  }
  dependsOn: [ appiMetricsPublisher ]
}

resource azMonLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: { loggerType: 'azureMonitor', isBuffered: false }
}

// Service-level ("All APIs") App Insights diagnostic; metrics:true is what lets llm-emit-token-metric publish.
resource appiDiag 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'applicationinsights'
  properties: {
    loggerId: appiLogger.id
    metrics: true
    alwaysLog: 'allErrors'
    httpCorrelationProtocol: 'W3C'
    verbosity: 'information'
    sampling: { samplingType: 'fixed', percentage: 100 }
  }
}

// API-level Azure Monitor diagnostic; largeLanguageModel populates ApiManagementGatewayLlmLog.
resource llmApiDiag 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = {
  parent: llmApi
  name: 'azuremonitor'
  properties: {
    loggerId: azMonLogger.id
    alwaysLog: 'allErrors'
    verbosity: 'information'
    logClientIp: true
    sampling: { samplingType: 'fixed', percentage: 100 }
    frontend: {
      request: { headers: [ 'x-client-app' ], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
    backend: {
      request: { headers: [], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
    largeLanguageModel: {
      logs: 'enabled'
      requests: { messages: 'all', maxSizeInBytes: 262144 }
      responses: { messages: 'all', maxSizeInBytes: 262144 }
    }
  }
}

resource apimDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: apim
  name: 'apim-to-law'
  properties: {
    workspaceId: law.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      { category: 'GatewayLogs', enabled: true }
      { category: 'GatewayLlmLogs', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}
```

Notes/caveats:

* `CustomMetricsOptedInType` is not in bicep-types (BCP037, issue https://github.com/Azure/bicep-types-az/issues/2048); AI-Gateway suppresses the warning and ARM honors it. The value may not round-trip on GET reliably (our `shared/apim.py` already warns about detection) — keep a manual portal fallback (App Insights → Usage and estimated costs → Custom metrics (Preview) → With dimensions).
* The `largeLanguageModel` property requires a recent API version (AI-Gateway uses `2024-06-01-preview`). The `2024-05-01` GA diagnostic may reject it — use preview for the API-level `azuremonitor` diagnostic.
* Adding `x-client-app` to `frontend.request.headers` puts the header in `ApiManagementGatewayLogs.RequestHeaders`, enabling ClientApp chargeback from logs too (not only metrics). Headers-only logging has negligible perf cost vs. bodies.
* LLM prompts/completions logging (`messages: 'all'`) is a data-governance decision; for a chargeback-only demo consider `messages: 'none'` if supported, or keep `all` to also demo audit. Token counts are logged regardless.
* Service-level vs API-level `applicationinsights` diagnostics: if both exist, API-level wins (docs "Loggers for a single API or all APIs"). Define metrics:true on whichever scope applies to the LLM APIs.
* 2021-05-01-preview is what AI-Gateway uses for diagnostic settings; `Microsoft.Insights/diagnosticSettings@2021-05-01-preview` remains the current Bicep version.

## 3. Workbook Bicep and chargeback KQL

### Workbook resource

```bicep
param workbookJson string = loadTextContent('workbooks/chargeback.json')

resource chargebackWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'ai-chargeback-workbook')
  location: location
  kind: 'shared'
  properties: {
    displayName: 'AI Gateway Chargeback'
    category: 'workbook'
    sourceId: law.id
    serializedData: replace(workbookJson, '{workspace-id}', law.id)
  }
}
```

Minimal `workbooks/chargeback.json` skeleton (schema https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json):

```json
{
  "version": "Notebook/1.0",
  "items": [
    { "type": 1, "content": { "json": "## AI Gateway chargeback (tokens × price)" }, "name": "title" },
    {
      "type": 3,
      "content": {
        "version": "KqlItem/1.0",
        "query": "<KQL from 3b below, escaped>",
        "size": 0,
        "timeContext": { "durationMs": 2592000000 },
        "queryType": 0,
        "resourceType": "microsoft.operationalinsights/workspaces",
        "visualization": "table"
      },
      "name": "cost-by-team"
    }
  ],
  "fallbackResourceIds": [ "{workspace-id}" ],
  "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json"
}
```

Tip: author the workbook in the portal once, then "Advanced editor → Gallery template" to export JSON; replace the workspace id with `{workspace-id}` placeholder.

### 3a. customMetrics (App Insights) chargeback

Workspace-based App Insights: query the component (`customMetrics`) or the LA workspace (`AppMetrics`, columns `Name, Sum, ItemCount, Properties`). Per user memory, `az monitor app-insights query` can return empty rows for workspace-based components — prefer `LogsQueryClient.query_resource(appi_id, ...)` (as `shared/apim.py` already does) or query `AppMetrics` in LA.

Metric names emitted: `Total Tokens`, `Prompt Tokens`, `Completion Tokens` (token-metrics-emitting README). Pre-aggregated rows → use `valueSum`, not `value`.

```kusto
// App Insights scope: tokens and cost per APIM subscription (team) / client app / day
let price = datatable(Metric:string, UsdPer1K:real)[
    'Prompt Tokens',     0.0004,   // placeholder: refresh from prices.azure.com (per 1K)
    'Completion Tokens', 0.0016    // placeholder
];
customMetrics
| where timestamp > ago(30d)
| where name in ('Prompt Tokens', 'Completion Tokens')
| extend Team = tostring(customDimensions['Subscription ID']),
         ClientApp = tostring(customDimensions['ClientApp']),
         ApiId = tostring(customDimensions['API ID'])
| summarize Tokens = sum(valueSum) by Day = bin(timestamp, 1d), Team, ClientApp, Metric = name
| join kind=inner price on Metric
| extend CostUsd = Tokens / 1000.0 * UsdPer1K
| summarize PromptTokens = sumif(Tokens, Metric == 'Prompt Tokens'),
            CompletionTokens = sumif(Tokens, Metric == 'Completion Tokens'),
            CostUsd = round(sum(CostUsd), 4)
          by Day, Team, ClientApp
| order by Day asc, CostUsd desc
```

LA workspace equivalent: `AppMetrics | where Name in (...) | extend Team = tostring(Properties['Subscription ID']) | summarize Tokens = sum(Sum) ...`.

Limitation: `customMetrics` has no model/deployment dimension unless added (e.g. `<dimension name="Model" value="@(...)"/>` — but the request body is needed; simpler to rely on logs for per-model pricing). With a single model deployment the datatable price is exact.

### 3b. ApiManagementGatewayLlmLog ⨝ ApiManagementGatewayLogs chargeback (recommended source of truth)

Columns (https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog): `CorrelationId, DeploymentName, ModelName, PromptTokens, CompletionTokens, TotalTokens, IsStreamCompletion, SequenceNumber, RequestMessages, ResponseMessages, OperationName, ApiVersion, Region, TimeGenerated`.
Gateway log columns (https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewaylogs): `CorrelationId, ApimSubscriptionId, ProductId, ApiId, UserId, ResponseCode, RequestHeaders, LastErrorReason, TotalTime, BackendResponseCode`.

`ApimSubscriptionId` holds the subscription entity name (sid, e.g. `team-retail`) and `ProductId` the product name — which is why AI-Gateway joins `SUBSCRIPTION_QUOTA_CL.Subscription` directly on it.

```kusto
let price = datatable(Model:string, InUsdPer1K:real, OutUsdPer1K:real)[
    'gpt-4.1-mini', 0.0004, 0.0016,   // placeholders; per 1K tokens, refresh from Retail Prices API
    'gpt-4o-mini',  0.00015, 0.0006
];
let llm = ApiManagementGatewayLlmLog
    | where TimeGenerated > ago(30d)
    | where DeploymentName != ''                       // header row only (one per request)
    | project CorrelationId, TimeGenerated, Model = coalesce(ModelName, DeploymentName), DeploymentName,
              PromptTokens, CompletionTokens, TotalTokens;
let gw = ApiManagementGatewayLogs
    | where TimeGenerated > ago(30d)
    | project CorrelationId, Team = ApimSubscriptionId, Product = ProductId, ApiId, ResponseCode,
              ClientApp = tostring(RequestHeaders['x-client-app']);
llm
| join kind=leftouter gw on CorrelationId
| join kind=leftouter price on Model
| extend CostUsd = PromptTokens / 1000.0 * InUsdPer1K + CompletionTokens / 1000.0 * OutUsdPer1K
| summarize Requests = count(), PromptTokens = sum(PromptTokens), CompletionTokens = sum(CompletionTokens),
            TotalTokens = sum(TotalTokens), CostUsd = round(sum(CostUsd), 4)
          by Day = bin(TimeGenerated, 1d), Product, Team, ClientApp, Model
| order by Day asc, CostUsd desc
```

Caveats:

* `ModelName` is the model returned by the backend (e.g. `gpt-4.1-mini-2025-04-14`); matching a price table may need `extract` or matching on `DeploymentName` like AI-Gateway. Validate against live rows before finalizing the datatable keys.
* Header key casing in `RequestHeaders` dynamic may be preserved as sent; test `RequestHeaders['x-client-app']` vs `['X-Client-App']`.
* Throttling visibility (429s never reach the backend, so no LLM log row and no token metric):

```kusto
ApiManagementGatewayLogs
| where TimeGenerated > ago(7d)
| summarize Total = count(), Throttled = countif(ResponseCode == 429),
            Blocked = countif(ResponseCode == 403 or ResponseCode == 400)
          by bin(TimeGenerated, 1h), Team = ApimSubscriptionId, Product = ProductId
| extend ThrottleRate = round(100.0 * Throttled / Total, 1)
```

* Ingestion latency: LA resource logs typically 2-5+ minutes; App Insights custom metrics a few minutes. The CI chart job should run separately (or after a delay) from the traffic job.

## 4. Products + subscriptions per team, and key retrieval in CI

```bicep
param teams array = [
  { name: 'team-retail',  displayName: 'Retail',  tpm: 4000, dailyQuota: 200000 }
  { name: 'team-finance', displayName: 'Finance', tpm: 2000, dailyQuota: 100000 }
  { name: 'team-hr',      displayName: 'HR',      tpm: 500,  dailyQuota: 20000 }   // deliberately tight → 429s
]

@batchSize(1)
resource products 'Microsoft.ApiManagement/service/products@2024-05-01' = [for t in teams: {
  parent: apim
  name: t.name
  properties: {
    displayName: t.displayName
    description: 'AI chargeback product for ${t.displayName}'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}]

@batchSize(1)
resource productApis 'Microsoft.ApiManagement/service/products/apiLinks@2024-05-01' = [for (t, i) in teams: {
  parent: products[i]
  name: '${t.name}-llm'
  properties: { apiId: llmApi.id }
}]

@batchSize(1)
resource productPolicies 'Microsoft.ApiManagement/service/products/policies@2024-05-01' = [for (t, i) in teams: {
  parent: products[i]
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: '<policies><inbound><base /><llm-token-limit counter-key="@(context.Subscription.Id)" tokens-per-minute="${t.tpm}" token-quota="${t.dailyQuota}" token-quota-period="Daily" estimate-prompt-tokens="false" retry-after-header-name="Retry-After" remaining-tokens-header-name="remaining-tokens" /></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
  }
}]

@batchSize(1)
resource subs 'Microsoft.ApiManagement/service/subscriptions@2024-05-01' = [for (t, i) in teams: {
  parent: apim
  name: t.name                                  // sid = team name → ApimSubscriptionId / 'Subscription ID' dimension
  properties: {
    displayName: '${t.displayName} team'
    scope: products[i].id                       // or '/products/${t.name}'
    state: 'active'
    allowTracing: false
  }
  dependsOn: [ productApis, productPolicies ]
}]
```

Design notes:

* Name the subscription sid = team name so `Subscription ID` dimension and `ApimSubscriptionId` show `team-retail` rather than a GUID — the dashboards become self-explanatory.
* Add `<dimension name="Product ID" />` to the `llm-emit-token-metric` policy (default dimension, no value needed) → 4 custom dims (API ID, Subscription ID, Product ID, ClientApp), under the 5-dimension limit. Cardinality: ~1 API × 3 subs × 3 products × ~6 apps ≪ 1,000 series.
* Do NOT output keys from Bicep (AI-Gateway does, with lint suppression). Deployment outputs are readable to anyone with deployment read access.

Key retrieval (https://learn.microsoft.com/en-us/rest/api/apimanagement/subscription/list-secrets): `POST https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{rg}/providers/Microsoft.ApiManagement/service/{apim}/subscriptions/{sid}/listSecrets?api-version=2024-05-01` → `{ "primaryKey": "...", "secondaryKey": "..." }`.

Required permission: `Microsoft.ApiManagement/service/subscriptions/listSecrets/action` (included in API Management Service Contributor `312a565d-c81f-4fd8-895a-4e21e48d571c`; least privilege = custom role with that action + read, scoped to the APIM instance).

```yaml
- name: Fetch team keys (masked)
  shell: bash
  run: |
    set -euo pipefail
    base="/subscriptions/${AZ_SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}"
    for team in team-retail team-finance team-hr; do
      key=$(az rest --method post \
        --url "https://management.azure.com${base}/subscriptions/${team}/listSecrets?api-version=2024-05-01" \
        --query primaryKey -o tsv)
      echo "::add-mask::${key}"
      var="KEY_$(echo "${team}" | tr 'a-z-' 'A-Z_')"
      echo "${var}=${key}" >> "$GITHUB_ENV"
    done
```

`::add-mask::` must be emitted before any other output of the value; after masking, writing to `$GITHUB_ENV` keeps it masked in later steps' logs. Safer alternative: fetch keys inside the Python script via `azure-mgmt-apimanagement` / REST with `DefaultAzureCredential` (OIDC login), so keys never touch the shell or env file.

## 5. Traffic generator design

GitHub Actions scheduling facts (https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule):

* Shortest interval: once every 5 minutes. Runs on default branch only, UTC by default (optional `timezone:` supported).
* Delays/drops under load, especially at the top of the hour → pick odd minutes (e.g. `7,37 * * * *`).
* Public repos: scheduled workflows auto-disabled after 60 days without repository activity (re-enable manually or via a commit that changes the cron). Notifications go to the user who last edited the cron.

Workload model (realistic chargeback shape):

| Team (sid) | Product | Client apps (`x-client-app`) | Share of calls | Prompt profile |
| --- | --- | --- | --- | --- |
| team-retail | team-retail | `storefront-bot`, `catalog-enricher` | 50% | short chat + medium product descriptions |
| team-finance | team-finance | `invoice-summarizer`, `analyst-copilot` | 35% | long documents, longer completions |
| team-hr | team-hr | `policy-qa` | 15% + burst | short Q&A, burst phase to hit TPM → 429 |

Budget guardrails (defense in depth):

1. Script: `MAX_REQUESTS` per run, `max_tokens` per call (e.g. 64-400), hard stop when cumulative `usage.total_tokens` ≥ `RUN_TOKEN_BUDGET`.
2. APIM: per-product `llm-token-limit` TPM + daily `token-quota` (above) caps worst case even if the script misbehaves.
3. Foundry deployment capacity (TPM) set low (e.g. 20-50K TPM).
4. Workflow `timeout-minutes` and `concurrency: { group: traffic, cancel-in-progress: false }` to avoid overlapping runs.

Rough cost bound: 3 teams × 40 req × ~800 tokens ≈ 96K tokens/run; at 2 runs/hour ≈ 4.6M tokens/day → cents/day on a mini model at retail pricing. Tune down for long-running demos.

Script skeleton (`tools/traffic/generate_traffic.py`):

```python
import os, random, time, json, requests

GATEWAY = os.environ["APIM_GATEWAY_URL"].rstrip("/")
PATH = os.environ.get("LLM_API_PATH", "llm")          # APIM API path
DEPLOYMENT = os.environ.get("DEPLOYMENT", "gpt-4.1-mini")
API_VERSION = os.environ.get("AOAI_API_VERSION", "2024-10-21")
RUN_TOKEN_BUDGET = int(os.environ.get("RUN_TOKEN_BUDGET", "100000"))
MAX_REQUESTS = int(os.environ.get("MAX_REQUESTS", "120"))

TEAMS = {
    "team-retail":  {"key": os.environ["KEY_TEAM_RETAIL"],  "apps": ["storefront-bot", "catalog-enricher"], "weight": 50},
    "team-finance": {"key": os.environ["KEY_TEAM_FINANCE"], "apps": ["invoice-summarizer", "analyst-copilot"], "weight": 35},
    "team-hr":      {"key": os.environ["KEY_TEAM_HR"],      "apps": ["policy-qa"], "weight": 15},
}
TOPICS = ["return policy", "quarterly variance", "parental leave", "shipping delays", "expense audit"]

def prompt(size: str) -> str:
    base = f"Summarize key considerations about {random.choice(TOPICS)}."
    filler = " Include context on stakeholders, risks, and next steps." * {"s": 1, "m": 8, "l": 30}[size]
    return base + filler

def call(team: str, cfg: dict, size: str, max_tokens: int):
    url = f"{GATEWAY}/{PATH}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
    headers = {"Ocp-Apim-Subscription-Key": cfg["key"], "x-client-app": random.choice(cfg["apps"])}
    body = {"messages": [{"role": "user", "content": prompt(size)}], "max_tokens": max_tokens}
    r = requests.post(url, headers=headers, json=body, timeout=60)
    used = r.json().get("usage", {}).get("total_tokens", 0) if r.status_code == 200 else 0
    return r.status_code, used

def main():
    spent, stats = 0, {}
    names = list(TEAMS)
    weights = [TEAMS[t]["weight"] for t in names]
    for i in range(MAX_REQUESTS):
        if spent >= RUN_TOKEN_BUDGET:
            break
        team = random.choices(names, weights)[0]
        size = random.choices(["s", "m", "l"], [60, 30, 10])[0]
        code, used = call(team, TEAMS[team], size, random.randint(64, 400))
        spent += used
        stats.setdefault(team, {}).setdefault(str(code), 0)
        stats[team][str(code)] += 1
        time.sleep(random.uniform(0.2, 1.5))
    # Burst for team-hr to exceed its low TPM and surface 429s (bounded by APIM limit, not backend).
    for _ in range(int(os.environ.get("HR_BURST", "15"))):
        code, used = call("team-hr", TEAMS["team-hr"], "l", 400)
        spent += used
        stats["team-hr"][str(code)] = stats["team-hr"].get(str(code), 0) + 1
    print(json.dumps({"tokens": spent, "status_by_team": stats}, indent=2))  # never print keys

if __name__ == "__main__":
    main()
```

Notes: never log headers; print only aggregated status codes. For `openai` SDK use `AzureOpenAI(azure_endpoint=f"{GATEWAY}/{PATH}", api_key=key, api_version=...)` only if the API's `subscriptionKeyParameterNames.header` is `api-key` (AI-Gateway pattern); otherwise pass `default_headers={"Ocp-Apim-Subscription-Key": key}`.

Workflow skeleton (`.github/workflows/traffic-generator.yml`):

```yaml
name: ai-gateway-traffic
on:
  schedule:
    - cron: '7,37 * * * *'        # every 30 min, off the top of the hour
  workflow_dispatch:
    inputs:
      max_requests: { description: 'Max requests', default: '120' }
      token_budget: { description: 'Run token budget', default: '100000' }
permissions:
  id-token: write
  contents: read
concurrency:
  group: ai-gateway-traffic
  cancel-in-progress: false
jobs:
  traffic:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    environment: demo
    env:
      AZ_SUB: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      RG: ${{ vars.RESOURCE_GROUP }}
      APIM: ${{ vars.APIM_NAME }}
      APIM_GATEWAY_URL: ${{ vars.APIM_GATEWAY_URL }}
      MAX_REQUESTS: ${{ inputs.max_requests || '120' }}
      RUN_TOKEN_BUDGET: ${{ inputs.token_budget || '100000' }}
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install requests
      - name: Fetch team keys (masked)
        shell: bash
        run: |  # see section 4 loop
          ...
      - run: python tools/traffic/generate_traffic.py
```

Keep-alive for the 60-day rule: a separate monthly workflow is NOT repository activity by itself in all cases; simplest is documenting manual re-enable, or scheduling from a private repo (rule applies to public repos).

## 6. Screenshot automation options

| Option | CI feasibility | Notes |
| --- | --- | --- |
| Playwright against Azure portal (App Insights Metrics, workbook) | Not feasible unattended | Portal requires interactive Entra sign-in; service principals / OIDC workload identities cannot sign in to the portal UI; MFA/Conditional Access block headless user login; storing a user password in CI is a security anti-pattern. Works only interactively on a dev box (per user memory: `run_playwright_code` + `page.screenshot({path})` persists files). |
| Azure Managed Grafana image renderer | Possible but extra cost/infra | Grafana render API can produce PNGs with a service-account token; adds a paid resource. Out of scope for a lab. |
| KQL via `azure-monitor-query` `LogsQueryClient` → pandas → matplotlib PNG | Feasible, recommended | Runs with the same OIDC login (`DefaultAzureCredential` picks up `azure/login` az CLI creds). Needs Log Analytics Reader on the workspace (+ Reader on App Insights for `query_resource`). AI-Gateway token-metrics-emitting lab already plots customMetrics with matplotlib. |
| Export workbook as image via API | Not available | Workbooks have no render-to-image REST API. |

Recommended approach:

1. `report-charts.yml` scheduled daily (e.g. `17 6 * * *`) + `workflow_dispatch`, independent from the traffic job (ingestion latency).
2. Python script runs the 3b chargeback KQL (tokens and cost by team/day), the 429 KQL, and the 3a customMetrics KQL by ClientApp; renders stacked bars (cost by team per day), line (tokens by ClientApp), bar (429 rate by team).
3. Upload PNGs + CSV as `actions/upload-artifact@v4` and write a Markdown summary table to `$GITHUB_STEP_SUMMARY` (embeds nicely, no commit noise). Optionally commit PNGs to `docs/images/chargeback/` on `workflow_dispatch` only (needs `contents: write`), avoiding a commit every day.
4. For the presentation deck, capture 1-2 real portal screenshots manually (workbook + App Insights Metrics split by `Subscription ID`) once data exists — label them as point-in-time.

## Key Discoveries Summary

* AI-Gateway's chargeback identity = APIM subscription (sid) scoped to a product tier; cost = LLM log tokens × price table joined on `CorrelationId` to gateway logs for `ApimSubscriptionId`. Price stored per 1K tokens, cost divides tokens by 1000 (recent 1000× bug fix — watch units).
* Two complementary data paths: App Insights `customMetrics` (near-real-time, dimensions incl. `ClientApp`, no per-model pricing unless dimensioned) and Log Analytics `ApiManagementGatewayLlmLog` (per request, model-aware, best for billing). Add `x-client-app` to the `azuremonitor` diagnostic frontend headers to get ClientApp in logs too.
* Throttled (429) requests have no token rows; report them from `ApiManagementGatewayLogs.ResponseCode`.
* Keys: fetch at runtime via `listSecrets` REST (api-version 2024-05-01) with OIDC identity + `::add-mask::`; do not output from Bicep.
* Cron min 5 min; avoid :00; public repos disable schedules after 60 days of inactivity.
* Portal screenshots are not automatable in CI; render charts from KQL with matplotlib and publish as artifacts/step summary.

## Recommended Next Research (not done)

- [ ] Validate `largeLanguageModel` diagnostic support on API version `2024-05-01` vs `2024-06-01-preview` against a live Basic v2 instance (`az deployment group what-if`).
- [ ] Confirm the exact `ModelName` values emitted for the chosen Foundry deployment to key the price table.
- [ ] Confirm `RequestHeaders` key casing for `x-client-app` in `ApiManagementGatewayLogs`.
- [ ] Pull current retail prices for the chosen model/region from `https://prices.azure.com/api/retail/prices` (serviceName 'Foundry Models', unitOfMeasure '1K') instead of placeholders.
- [ ] Decide least-privilege custom role for CI (listSecrets + Log Analytics Reader) vs. APIM Service Contributor.
- [ ] Verify whether `customMetrics.value` equals `valueSum` for APIM-emitted pre-aggregated rows in this tenant (use `valueSum` meanwhile).

## Clarifying Questions

1. Public or private repo? (60-day schedule auto-disable only applies to public repos.)
2. Should LLM request/response message bodies be logged (`messages: 'all'`) or only tokens, given data-governance messaging in the offering?
3. Team names/tiers: keep `team-retail/finance/hr`, or align with existing demo client apps (`claims-portal`, `analyst-copilot`)?
4. Commit rendered charts to the repo, or artifacts/step summary only?
5. Static price datatable in KQL (simple) vs. AI-Gateway-style `PRICING_CL` custom table + DCR (more realistic, more infra)?
