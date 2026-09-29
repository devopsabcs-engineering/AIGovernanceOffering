<!-- markdownlint-disable-file -->

> Historical inventory snapshot, reviewed on 2026-09-28. This describes existing code, including defects; it is not approval to preserve unsafe behavior. Implementation decisions and acceptance gates are consolidated in .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. Original content is retained as evidence; historical line references predate this notice.

# Current Repo Research: AIGovernanceOffering (as-is inventory)

Status: Complete

Scope: read-only analysis of `c:\src\GitHub\devopsabcs-engineering\AIGovernanceOffering` to inform Bicep, GitHub Actions (headless lab execution, teardown), and lab publishing. No repo files were modified.

Notebook cell references below are 1-based cell numbers as seen in the VS Code notebook editor (markdown + code). Python file references use line numbers.

## Research Questions

1. README summary: purpose, prerequisites, how labs run, assumed Azure resources, env vars.
2. requirements.txt contents.
3. shared/*.py: config, auth, apim, display, fixtures.
4. Each notebook: cells, dependencies, policies applied, outputs/charts, queries, hardcoded names.
5. Each policy XML: elements, named values, backends, metric dimensions.
6. tests/*.py: what they test and how they run.
7. docs/ and Presentation/ contents and conventions.
8. .github, workflows, infra, bicep, azd, .env.example, .gitignore.
9. APIM SKU, region, model deployments, Content Safety, App Insights mentions.

## 0. Top-level layout

```
.copilot-tracking/     (research only)
.env.example
.gitignore
README.md
requirements.txt
docs/ai-governance-flows.svg
notebooks/00-setup-and-validation.ipynb, demo1..demo4
policies/demo1-token-limit.xml, demo2-emit-token-metric.xml, demo3-content-safety.xml, demo4-resilient-pool.xml, demo4-mock-origin.xml
Presentation/Module 8 - Gateway and Metering Plane.pptx
shared/__init__.py, apim.py, auth.py, config.py, display.py, fixtures.py
tests/test_apim.py, test_config.py, test_notebooks.py
```

NOT present: `.github/`, any workflows, `infra/`, `*.bicep`, `azure.yaml` (azd), `.azure/`, `pyproject.toml`, `pytest.ini`, `setup.cfg`, `conftest.py`, `.vscode/`, `LICENSE` (README badge links to `LICENSE` but the file does not exist).

## 1. README.md summary

* Purpose (README.md L1-L25): "AI Governance Labs" - govern Microsoft Foundry models behind Azure API Management "with policy, not application code". Four labs: token limits/quotas, chargeback metering, bidirectional content safety, resilient backend pools. Each lab is a Python notebook that creates everything it needs **on an existing APIM instance**.
* Prerequisites (README.md L27-L55):
  * Existing APIM instance (notebooks never create APIM itself - only APIs, policies, products, subscriptions, backends, named values, loggers, diagnostics).
  * Azure CLI logged in (`az login`); code uses `AzureCliCredential` with fallback to `DefaultAzureCredential` (no interactive browser).
  * Python 3.10+.
  * Microsoft Foundry / Azure OpenAI resource with a chat-completion deployment (example `gpt-4o-mini`). Auth: APIM system-assigned MI with **Cognitive Services OpenAI User** (preferred) or API key fallback.
  * Demo 3: Azure AI Content Safety resource (kind "Content Safety"); APIM MI with **Cognitive Services User** (preferred) or key fallback.
  * Demo 4: APIM SKU supporting backend pools + circuit breakers (Basic v2, Standard v2, Premium v2, classic Standard/Premium). Optional extra model endpoints; otherwise one origin as three logical members; same model+version required.
* SKU matrix (README.md L57-L84): `llm-token-limit` and `llm-content-safety` supported on Developer, Basic, Basic v2, Standard, Standard v2, Premium, Premium v2 (not Consumption). Pools/circuit breaker: Basic v2, Standard v2, Premium v2, classic Standard, classic Premium (not Consumption, Developer, classic Basic). => **Basic v2 is the cheapest SKU that satisfies all four demos.**
* Getting started (README.md L86-L113): venv, `pip install -r requirements.txt`, `az login`, `jupyter notebook`; run `00-setup-and-validation.ipynb` first, which persists config to `.env` (gitignored). Precedence: env vars -> `.env` -> interactive prompt (persisted back to `.env`). Secrets masked.
* Demo template (README.md L125-L130): Scenario -> Isolation -> Configure (policy apply) -> Baseline -> Demonstrate -> Observe -> Reset/Cleanup -> Talk track.
* Named value convention (README.md L152-L165): named value id == display name == lowercase `{{token}}`; `ensure_named_value` raises otherwise. Named values interpolated into `condition`/`set-body` expressions must be `secret=False`.
* Demo sections (README.md L167-L380) - summarized under section 4 below. README says final cleanup removes "APIs, products, subscriptions, backends, named values, loggers, and diagnostics" - the actual cleanup cell does NOT delete products, loggers, or several named values (see Gaps).

### Environment variables (authoritative list = `_ENV_KEYS` in shared/config.py L79-L105; documented in `.env.example`)

| Env var | Config field | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| AZURE_SUBSCRIPTION_ID | subscription_id | `az account show` result | no | fallback via subprocess (auth.py L44-L58) |
| APIM_RESOURCE_GROUP | resource_group | "" | yes | |
| APIM_NAME | apim_name | "" | yes | |
| AOAI_ENDPOINT | aoai_endpoint | "" | yes | must be resource root, no path (validate_config L282-L290) |
| AOAI_DEPLOYMENT | aoai_deployment | "" | yes | deployment name |
| AOAI_KEY | aoai_key (secret) | None | no | blank = managed identity |
| AOAI_API_VERSION | aoai_api_version | `2024-10-21` | no | classic style only |
| AOAI_API_STYLE | aoai_api_style | `v1` | no | `v1` (Foundry `/openai/v1/chat/completions`, model in body) or `classic` (`/openai/deployments/{d}/chat/completions?api-version=`) |
| APP_INSIGHTS_NAME | app_insights_name | None | Demo 2 | used to build resource id in APIM RG (assumes AI is in the APIM RG) |
| APP_INSIGHTS_RESOURCE_ID | app_insights_resource_id | None | Demo 2 | |
| APP_INSIGHTS_CONNECTION_STRING | app_insights_connection_string (secret) | None | Demo 2 | required to create logger |
| CONTENT_SAFETY_ENDPOINT | content_safety_endpoint | "" | Demo 3 | resource root, no path |
| CONTENT_SAFETY_KEY | content_safety_key (secret) | None | no | blank = MI |
| CONTENT_SAFETY_BLOCKLIST_ID | content_safety_blocklist_id | None | no | policy block is commented out regardless |
| CONTENT_SAFETY_THRESHOLD_HATE/SELFHARM/SEXUAL/VIOLENCE | thresholds | `4` | no | int 0-7 validated |
| DEMO4_PTU_EAST_ENDPOINT / DEMO4_PTU_CENTRAL_ENDPOINT / DEMO4_PAYG_ENDPOINT | demo4_* | fall back to AOAI_ENDPOINT | no | HTTPS root validated |
| DEMO4_PTU_EAST_DEPLOYMENT / DEMO4_PTU_CENTRAL_DEPLOYMENT / DEMO4_PAYG_DEPLOYMENT | demo4_*_deployment | fall back to AOAI_DEPLOYMENT | no | all must be equal |
| DEMO_RUN | demo_run | random 8-hex | no | counter-key suffix for Demo 1; header x-demo-run elsewhere |

`.env.example` examples reveal original lab environment naming: APIM RG/name `AIGovernanceOffering`, Foundry endpoint `https://aigovernanceoffering.services.ai.azure.com`, deployment `gpt-4o`, Content Safety `https://aigovernanceoffering-cs.cognitiveservices.azure.com`, App Insights `ApimAppInsights`. No region is specified anywhere.

## 2. requirements.txt

```
azure-identity>=1.16.0
azure-monitor-query>=2.0.0
requests>=2.31.0
python-dotenv>=1.0.1
pandas>=2.0.0
matplotlib>=3.7.0
ipykernel>=6.29.0
jupyter>=1.0.0
tabulate>=0.9.0
```

No `pytest`, `papermill`, or `nbconvert` pin (nbconvert comes transitively via `jupyter`). No APIM/ARM management SDK - all control plane is raw ARM REST via `requests`.

## 3. shared/*.py

### shared/config.py

* `REPO_ROOT`/`ENV_PATH` = repo root `.env` (L21-L22). `SECRET_FIELDS` L25. `DEFAULT_CONTENT_SAFETY_THRESHOLD="4"` L31. `API_STYLES=("v1","classic")` L39.
* `WorkshopConfig` dataclass L43-L76 (fields as in env table); `as_display_dict` masks secrets.
* `load_config(interactive=True)` L130-L241: loads `.env` (override=False), reads env vars, then if interactive prompts for missing RG, APIM name, AOAI endpoint, AOAI deployment. **Prompt quirks relevant to CI:**
  * L216: prompts for AOAI_KEY if `cfg.aoai_key is None` AND `AOAI_KEY` line not present in `.env` (an env var alone with empty value does not suppress it).
  * L225: prompts for AOAI_API_STYLE whenever `AOAI_API_STYLE` is not a line in `.env` - **even if the env var is set**.
  * Always persists `subscription_id` and `demo_run` to `.env` (writes/creates the file).
* `persist_demo_run` L256. `validate_config` L261-L290 (required RG/APIM/endpoint/deployment; style; endpoint root).
* `ensure_content_safety_config` L293-L317: prompts for CONTENT_SAFETY_ENDPOINT if empty; for CONTENT_SAFETY_KEY if None and not in `.env` (L308).
* `validate_content_safety_config` L320-L352.
* `ensure_resilient_pool_config` L355-L394: prompts for each of the six DEMO4_* values if empty and not a line in `.env`, then defaults to AOAI values.
* `validate_resilient_pool_config` L397+: HTTPS root check and same-deployment rule.
* CI implication: headless runs must pre-write a `.env` containing at least `AOAI_KEY=`, `AOAI_API_STYLE=v1`, `CONTENT_SAFETY_KEY=`, and the six `DEMO4_*=` lines (empty allowed), otherwise `input()`/`getpass()` (L121-L125) is called and nbconvert/papermill fails with StdinNotImplementedError.

### shared/auth.py

* `ARM_SCOPE = https://management.azure.com/.default` (L16).
* `get_credential()` L19-L34: `AzureCliCredential` (forces a token fetch), fallback `DefaultAzureCredential(exclude_interactive_browser_credential=True)`; lru_cached.
* `get_arm_token()` L37-L41. `get_current_subscription_id()` L44-L58 runs `az account show` without shell (on Windows `az` is `az.cmd`, which may raise and return None - harmless if AZURE_SUBSCRIPTION_ID is set). `mask_secret` L61-L67.
* Auth model: **Entra/ARM bearer for all control-plane calls; no keys for management.** Data plane uses APIM subscription keys fetched via ARM `listSecrets`. APIM->AOAI and APIM->Content Safety use APIM system-assigned MI by default, keys as fallback.
* In GitHub Actions, `azure/login` (OIDC) makes `AzureCliCredential` work as-is.

### shared/apim.py (ARM REST, idempotent PUT)

* Constants: `ARM_BASE` L20; `API_VERSION = "2024-06-01-preview"` L21 (default for all calls); `APIM_PREVIEW_API_VERSION = "2025-09-01-preview"` L22 (diagnostics only). Async polling on 202 (L103-L120, 300 s timeout).
* Headers: `Authorization: Bearer <ARM token>`, `Content-Type: application/json` (L43-L48).
* Functions (all under `.../providers/Microsoft.ApiManagement/service/{apim}`):
  * `ensure_api` L123 - PUT `/apis/{id}` with displayName, path, protocols `["https"]`, subscriptionRequired, optional serviceUrl.
  * `ensure_operation` L151 - PUT `/apis/{api}/operations/{op}` (method, urlTemplate).
  * `ensure_backend` L178 - PUT `/backends/{id}`: url, protocol `http`, tls validation on, optional `credentials` (`managedIdentity.resource` or `header` dict), optional `circuitBreaker`.
  * `ensure_backend_pool` L223 - PUT `/backends/{id}` with `type: Pool`, `pool.services[]` of `{id: ARM id, priority, weight}` (expands short names to ARM ids).
  * `ensure_named_value` L283 - PUT `/namedValues/{id}` (displayName must equal id).
  * `ensure_product` L322 - PUT `/products/{id}` (subscriptionRequired, state published).
  * `ensure_product_api_link` L347 - PUT `/products/{p}/apis/{a}` (classic link endpoint).
  * `ensure_subscription` L373 - PUT `/subscriptions/{id}` scope `/products/{p}` or `/apis/{a}`, state active.
  * `list_loggers` L401, `get_logger` L412, `ensure_logger` L426 - PUT `/loggers/{id}` loggerType `applicationInsights`, `isBuffered: true`, optional `resourceId`, **requires** `credentials.connectionString` (raises if missing).
  * `get_app_insights_for_apim` L468 - first AI logger on the service.
  * `ensure_api_diagnostic` L486 - PUT `/apis/{api}/diagnostics/applicationinsights` (api-version 2025-09-01-preview): `alwaysLog: allErrors`, `metrics: true` (required for custom metrics), sampling 100 % fixed, `largeLanguageModel.requests/responses {messages: all, maxSizeInBytes: 8192}`; retries without LLM block on a matching 400.
  * `get_api_diagnostic` L545. `app_insights_resource_id` L567 (assumes AI in the APIM RG).
  * `check_custom_metric_dimensions_enabled` L579 - GET `{aiId}/currentbillingfeatures?api-version=2015-05-01`; returns PASS only if a feature named `metricdimensions`/`custommetricdimensions` appears; otherwise MANUAL with portal instructions ("Usage and estimated costs -> Alerting on custom metric dimensions").
  * `query_token_metrics` L657 -> `query_app_insights_token_metrics` L730: `azure.monitor.query.LogsQueryClient.query_resource(<AI resource id>, KQL)`:

    ```kusto
    customMetrics
    | where timestamp between (datetime(start) .. datetime(end))
    | where name in ('<candidate>')
    | where tostring(customDimensions['Subscription ID']) == '<apim sub id>'   // optional
    | extend dimension_value = tostring(customDimensions['ClientApp'])
    | summarize total=sum(value) by bin(timestamp, 5m), metric_name=name, dimension_value
    | order by timestamp asc
    ```

    Needs the caller to have read access to App Insights logs (e.g. Monitoring Reader / Log Analytics Reader on the AI component or workspace).
  * `set_api_policy` L783 - PUT `/apis/{api}/policies/policy` `{format: xml, value}`. `get_api_policy` L801 (`format=rawxml`).
  * `get_gateway_url` L836. `get_subscription_key` L849 - POST `/subscriptions/{id}/listSecrets` -> `primaryKey`.
  * Deletes: `delete_api_if_exists` L870 (`deleteRevisions=true`), `delete_subscription_if_exists` L892, `delete_named_value_if_exists` L911, `delete_apim_resource_if_exists` L930 (generic relative path). `get_service` L950.
* Policies are deployed **only via ARM REST from notebooks** - no Bicep/ARM templates/SDK.

### shared/display.py

`header` L19, `banner` L24 (HTML colored bar), `show_table` L45 (pandas DataFrame via `IPython.display`), `mask_key_in_url` L59, `plot_remaining_tokens` L66 (matplotlib line chart, Demo 1), `plot_token_series_by_dimension` L88 (matplotlib time series by ClientApp, Demo 2). Falls back to `print` outside Jupyter. Charts use `plt.show()` (inline outputs when executed via nbconvert/papermill; nothing saved to disk).

### shared/fixtures.py

`FIXTURE_SET_VERSION = "2025-01-demo3-v1"` (L21); `DEMO3_FIXTURES` (L24+) with 4 cases: `safe_business_prompt` (200), `prompt_injection` (403), `harm_threshold` (403, mild placeholder, may not trip), `streaming_completion` ("STREAM STOPS", may not trip).

## 4. Notebooks

All notebooks: `sys.path.append("..")`, relative file reads `../policies/*.xml` => must execute with cwd = `notebooks/`. Kernel `python3` ("Python 3"). No stored outputs (clean), **no cell tagged `parameters`**. All call `config.load_config(interactive=True)`.

### 00-setup-and-validation.ipynb (11 cells, read-only against Azure)

* Cell 2: imports. Cell 4: `subprocess.run(["az","account","show","-o","json"], shell=True)` (on Linux `shell=True` with a list runs only `az`, so it succeeds without showing the account - harmless but misleading). Cell 6: `load_config` + `validate_config` + masked config table. Cell 8: `apim.get_service` -> table of name/location/SKU/gatewayUrl/provisioningState; warnings if SKU not in `{Developer, Basic, BasicV2, Standard, StandardV2, Premium, PremiumV2}` (llm-token-limit) or `{BasicV2, StandardV2, PremiumV2, Standard, Premium}` (pools). Cell 10: Content Safety endpoint validation/warnings (no Azure call). No resources created.

### demo1-token-limits.ipynb (25 cells)

* Hardcoded names (cell 3): API `demo1-openai-api` (path `demo1-openai`), backend `demo1-openai-backend`, product `demo1-token-governance-product` (display "Demo1-Token-Governance"), subscription `demo1-token-governance-sub`, named values `demo1-aoai-key` (secret, only if key), `demo1-tokens-per-minute` = `200`, `demo1-daily-token-cap` = `400` (non-secret). Operation `chat-completions` POST `/openai/v1/chat/completions` (v1) or `/openai/deployments/{d}/chat/completions` (classic).
* Cells 5-9: ensure backend (url = AOAI_ENDPOINT), API (serviceUrl = AOAI endpoint), operation, named values, product + link + subscription (scope product).
* Cells 11-12: load `policies/demo1-token-limit.xml`; if AOAI_KEY set, regex-swap MI block for `api-key: {{demo1-aoai-key}}`; PUT at API scope.
* Cell 14: gateway URL + subscription key; helper `call_chat_completion` (headers `Ocp-Apim-Subscription-Key`, `x-demo-run`; body uses `max_tokens`). Captures `tokens-consumed`, `remaining-tokens`, `remaining-quota-tokens`, `Retry-After`.
* Cell 16 baseline table. Cell 18 burst up to 20 calls until 429. Cell 19 chart `plot_remaining_tokens`. Cell 21 loop up to 60 iterations / 180 s wall clock (plus Retry-After sleeps) until 403. Cell 23 consolidated table. Cell 25 reset: new DEMO_RUN persisted, follow-up call.
* No App Insights/KQL. No cleanup.

### demo2-token-metrics.ipynb (28 cells)

* Names (cell 3): API `demo2-metering-api` (path `demo2-metering`), backend `demo2-openai-backend`, product `demo2-metering`, subscription `demo2-metering-sub`, named value `demo2-aoai-key` (optional), logger `demo2-application-insights`, metric namespace `module8`, ClientApp allow-list `{claims-portal, analyst-copilot}`.
* Cell 5 preflight: discovers AI resource id (env or existing APIM logger), `get_api_diagnostic`, `check_custom_metric_dimensions_enabled`, allow-list check -> table + banners.
* Cells 7-9: backend, API + operation, product/link/subscription, optional key named value.
* Cell 10: if `APP_INSIGHTS_CONNECTION_STRING` set -> `ensure_logger(demo2-application-insights, resourceId, connectionString)` (APIM auto-creates `Logger-Credentials--*` named values each PUT); else reuse existing AI logger; then `ensure_api_diagnostic` (metrics: true, LLM logging).
* Cells 12-13: load/swap/apply `policies/demo2-emit-token-metric.xml`.
* Cell 15 helper (headers `x-client-app`, `x-demo-run`; captures usage). Cell 17 baseline. Cell 19: 5x `claims-portal` + 3x `analyst-copilot` (1 s spacing) + groupby table.
* Cell 21: re-checks diagnostic exists with `metrics: true`, policy contains `llm-emit-token-metric` (fail fast, raises RuntimeError), then KQL polling via `apim.query_token_metrics` with backoff 15/30/45/60/75 s (up to ~225 s) across metric name candidates (`prompt_tokens`/`Prompt Tokens`/`PromptTokens`, etc.). Table + `plot_token_series_by_dimension` chart.
* Cell 23: acceptance table PASS 01 (two ClientApp series), PASS 02 (prompt+completion == total), PASS 03 (subscription filter isolates). Cell 25: builds streaming body only (not sent). Cell 28: regenerates DEMO_RUN.
* Needs: Application Insights (connection string + resource id), "custom metric dimensions" enabled on AI, caller read access to AI logs.

### demo3-content-safety.ipynb (21 cells)

* Names (cell 3): API `demo3-content-safety-api` (path `demo3-content-safety`), backends `demo3-openai-backend`, `demo3-content-safety-backend`, product `demo3-content-safety`, subscription `demo3-content-safety-sub`, named values `demo3-aoai-key` (opt), `demo3-content-safety-key` (opt, secret; created but not referenced by the policy - backend credentials carry the key), `demo3-content-safety-blocklist-id` (opt), `demo3-content-safety-threshold-{hate,selfharm,sexual,violence}` (non-secret).
* Cell 5 preflight: APIM reachable, AOAI values, CS config validation, MI role reminder (MANUAL if no key).
* Cell 7: Content Safety backend url = CONTENT_SAFETY_ENDPOINT with `credentials.managedIdentity.resource = https://cognitiveservices.azure.com` or `credentials.header.Ocp-Apim-Subscription-Key`.
* Cells 8-9: API/operation, product/link/subscription, named values. Cells 11-12: load/swap/apply `policies/demo3-content-safety.xml`.
* Cell 14 fixture table. Cell 16 helper (captures `x-content-safety-decision`, `x-content-safety-reason`). Cell 18 matrix (safe 200 / injection 403 / harm 403 or NOT TRIPPED). Cell 20 streaming (`stream: true`, SSE parsing; PASS if stream ends without `data: [DONE]`). No cleanup. No KQL.

### demo4-resilient-pool.ipynb (25 cells)

* Names (cell 3): API `demo4-resilient-pool-api` (path `demo4-resilient-pool`), product `demo4-resilient-pool`, subscription `demo4-resilient-pool-sub`, mock API `demo4-mock-origin-api` (path `demo4-mock-origin`), mock subscription `demo4-mock-origin-sub` (scope `/apis/demo4-mock-origin-api`), pool `demo4-aoai-pool`, member backends `demo4-ptu-east` (p1,w2), `demo4-ptu-central` (p1,w1), `demo4-payg` (p2,w1). `CIRCUIT_TRIP_SECONDS=60`, `RECOVERY_WAIT_SECONDS=65`.
* Cell 5: preflight SKU check; **raises** if SKU not in `{BasicV2, StandardV2, PremiumV2, Standard, Premium}`.
* Cell 7: named values `demo4-mock-fault-{east,central,payg}` = `healthy`, `demo4-mock-retry-after-{member}` = `60`; mock API (serviceUrl = gateway URL) + subscription; `demo4-mock-origin-key` (secret named value = mock sub primary key); mock operations POST `/east`, `/central`, `/payg`; apply `policies/demo4-mock-origin.xml`; member backends url `{gateway}/demo4-mock-origin/{member}` with circuit breaker and `credentials.header.Ocp-Apim-Subscription-Key = ["{{demo4-mock-origin-key}}"]`; pool backend.
  * Circuit breaker: rule `demo4-throttle-and-server-errors`, `failureCondition {count: 2, interval: PT1M, statusCodeRanges: [429-429, 500-599]}`, `tripDuration: PT1M`, `acceptRetryAfter: true`.
* Cell 8: client API + operation + product/link/subscription + optional `demo4-aoai-key`; apply `policies/demo4-resilient-pool.xml` (string-replace MI element with `api-key` header if key).
* Cell 10: fixed request, `call_pool`, `set_mock_member/fault_member/heal_member/heal_all`, `configure_mode("routing"|"inference")` (re-PUTs member backends to mock URLs or real AOAI endpoints), `member_table`.
* Cell 12 inference baseline (real AOAI). Cell 14 CALL 1. Cell 16 CALL 2 + 30 calls distribution. Cell 18 FAULT (12 + 6 + 12 calls; heal in finally). Cell 20 RECOVER (sleeps 65 s, 12 calls). Cell 22 heal all.
* Cell 25 teardown gated by hardcoded `REMOVE_WORKSHOP_ARTIFACTS = False`. Deletes: diagnostic `apis/demo2-metering-api/diagnostics/applicationinsights`; APIs demo1..demo4 + mock; subscriptions (5); backends (8); named values `demo1-tokens-per-minute`, `demo1-daily-token-cap`, `demo1-aoai-key`, `demo2-aoai-key`, `demo3-aoai-key`, `demo3-content-safety-key`, `demo4-aoai-key`, `demo4-mock-origin-key`, `demo4-mock-fault-*`, `demo4-mock-retry-after-*`. Never deletes APIM.
* Heads-up to verify at runtime: in routing mode the client-facing operation path (`/openai/v1/chat/completions`) is appended to the member backend URL `.../demo4-mock-origin/{member}`, while mock operations are `/east`, `/central`, `/payg`. The notebook is marked "Complete" so this presumably works, but CI should assert `x-served-by` is returned.

## 5. Policies (policies/*.xml)

| File | Scope | Elements | Backends | Named values | Other |
| --- | --- | --- | --- | --- | --- |
| demo1-token-limit.xml | API `demo1-openai-api` | `set-backend-service`, `authentication-managed-identity` (resource `https://cognitiveservices.azure.com`, output var `aoai-token`), `set-header Authorization Bearer`, **`llm-token-limit`** (counter-key `context.Subscription.Id + "-" + x-demo-run`, `tokens-per-minute`, `token-quota`, `token-quota-period="Daily"`, `estimate-prompt-tokens="false"`, headers `Retry-After`, `tokens-consumed`, `remaining-tokens`, `remaining-quota-tokens`) | `demo1-openai-backend` | `{{demo1-tokens-per-minute}}`, `{{demo1-daily-token-cap}}`, (`{{demo1-aoai-key}}` when key swap) | Not `azure-openai-token-limit` |
| demo2-emit-token-metric.xml | API `demo2-metering-api` | `set-backend-service`, MI auth + header, **`llm-emit-token-metric namespace="module8"`** in inbound | `demo2-openai-backend` | (`{{demo2-aoai-key}}`) | Dimensions: `API ID`, `Subscription ID`, `ClientApp` = header `x-client-app` default `unknown`. Needs API diagnostic with `metrics: true` + AI logger |
| demo3-content-safety.xml | API `demo3-content-safety-api` | `set-backend-service`, MI auth + header, **`llm-content-safety`** inbound (`shield-prompt="true"`, `enforce-on-completions="true"`, `categories output-type="EightSeverityLevels"` x4, blocklists commented) and outbound (`window-size="1000"`, `window-overlap-size="100"`, same categories); `on-error` `choose` on `context.LastError.Source == "llm-content-safety"` -> `return-response` 403 JSON + headers `x-content-safety-decision`, `x-content-safety-reason` | `demo3-openai-backend`, `demo3-content-safety-backend` | `{{demo3-content-safety-threshold-hate/selfharm/sexual/violence}}`, (`{{demo3-content-safety-blocklist-id}}` commented), (`{{demo3-aoai-key}}`) | CS backend auth set on backend entity |
| demo4-resilient-pool.xml | API `demo4-resilient-pool-api` | `set-backend-service backend-id="demo4-aoai-pool"`, `authentication-managed-identity` (no output var -> sets Authorization automatically), outbound/on-error `set-header x-demo4-routing` | `demo4-aoai-pool` (Pool) -> `demo4-ptu-east`, `demo4-ptu-central`, `demo4-payg` | (`{{demo4-aoai-key}}`) | No `retry` policy; resilience from pool + backend circuit breaker only |
| demo4-mock-origin.xml | API `demo4-mock-origin-api` | `choose` on `context.Operation.Id` + fault named values -> `return-response` 429 (`Retry-After`, `x-served-by`) or 200 chat-completion JSON (`x-served-by`); otherwise 404 | none | `{{demo4-mock-fault-east/central/payg}}`, `{{demo4-mock-retry-after-east/central/payg}}`, backend credential `{{demo4-mock-origin-key}}` | Named values used in expressions => must be non-secret |

Chargeback-relevant dimensions today: only `API ID`, `Subscription ID`, `ClientApp`. Not used: `User ID`, `Client IP`, `Operation ID`, `Product ID`, `Location`, `Gateway ID`, `Backend ID` (built-in dimensions available to `llm-emit-token-metric`), nor a CostCenter/tenant custom dimension. README/notebook guidance: <=5 custom dimensions, bounded values.

Policies NOT used anywhere: `azure-openai-token-limit`, `azure-openai-emit-token-metric`, `retry`, `rate-limit-by-key`, `llm-semantic-cache-*`.

## 6. tests/*.py

Framework: `unittest` classes (pytest-compatible). No Azure calls; no notebook execution. All tests import `shared` from repo root, so run from repo root with `python -m unittest discover -s tests -t .` or `python -m pytest tests` (plain `pytest` without `python -m` may fail to import `shared` because there is no conftest/pyproject). `pytest` is not in requirements.txt.

* tests/test_apim.py: default api-version is `2024-06-01-preview` (L11); XML structure of demo2 (L24, inbound metric, dimension names order), demo3 (L45, both directions, thresholds named-value tokens, no enforce-on-completions outbound, on-error choose), demo4 pool policy (L88) and mock origin (L103, 6+ return-responses, 3 throttles, x-served-by set); `ensure_backend` body (L141+, credentials, circuit breaker); pool ARM id expansion/validation (L213-L258); delete 404 behavior (L280); `ensure_logger` requirements (L296); `ensure_api_diagnostic` LLM fallback (L364); `get_api_policy` rawxml (L403); token metrics KQL via mocked `LogsQueryClient` (L430+).
* tests/test_config.py: Demo 4 pool defaults/mismatch/invalid endpoint; content safety validation (endpoint, path, thresholds).
* tests/test_notebooks.py: static JSON/AST checks - no code cell ends with a bare display helper expression; **README.md and all `.ipynb/.py/.xml` under notebooks, shared, policies, tests must not match regex `M8\.|\bslide\b|\bdeck\b` (case-insensitive)**; Demo 3 contains NOT TRIPPED handling; Demo 4 has four routing phase headings, `configure_mode("inference")`, acceptance sentence, `subscription_required=True`, `MOCK_BACKEND_CREDENTIALS`; Demo 4 fault/heal helpers write the expected named values (exec'd with mocks).
* Constraint for new work: README edits (e.g. lab site links) must avoid the words "slide"/"deck" and "M8.".

## 7. docs/ and Presentation/

* docs/ai-governance-flows.svg - single animated SVG (viewBox 1200x1230, Segoe UI font) embedded at top of README. No screenshots/images folder, no naming convention for images yet.
* Presentation/Module 8 - Gateway and Metering Plane.pptx - source material (Module 8). Not referenced by README (test forbids presentation words).
* `.gitignore` ignores `outputs/` - a natural home for executed notebooks/screenshots if they are not to be committed.

## 8. Repo infra/CI files

* `.github/`: absent. No workflows. No `infra/`, Bicep, ARM, Terraform, azd (`azure.yaml`).
* `.env.example`: present (documented above).
* `.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `.ipynb_checkpoints/`, `outputs/`, `.venv/`, `venv/`, `*.egg-info/`, `.DS_Store`.

## 9. SKU / region / models / Content Safety / App Insights mentions

* APIM SKU: none pinned; README requires Basic v2+ for Demo 4; 00 notebook and Demo 4 check `sku.name` (`BasicV2` etc.). APIM needs **system-assigned managed identity** enabled.
* Region: not mentioned anywhere.
* Models: README example `gpt-4o-mini`; `.env.example` example `gpt-4o`. Requests use `max_tokens` (not `max_completion_tokens`) -> choose a model accepting `max_tokens` (gpt-4o-mini / gpt-4o / gpt-4.1-mini); reasoning models (o-series, gpt-5) would reject it. `v1` style default implies a Foundry (AIServices) endpoint `*.services.ai.azure.com` (an `*.openai.azure.com` endpoint also works with `classic`). Streaming used in Demo 3.
* Content Safety: kind "ContentSafety", endpoint `*.cognitiveservices.azure.com`; APIM MI needs Cognitive Services User. (An AIServices account also exposes Content Safety APIs; the repo assumes a separate resource, but the backend only needs a root URL serving `/contentsafety/...` - reuse is possible but unverified.)
* App Insights: required for Demo 2 (logger via connection string; `isBuffered: true`); must have "custom metric dimensions" enabled; code reads `customMetrics` table via `LogsQueryClient.query_resource` on the AI component id. If AI has `DisableLocalAuth=true`, connection-string logger ingestion is rejected silently - keep local auth enabled or switch the logger to MI credentials.

## Consolidated Azure resource / config inventory (for Bicep)

Azure resources (outside APIM):

1. Resource group.
2. **APIM** - SKU `BasicV2` (minimum for all four labs), **system-assigned MI enabled**, publisher email/name. Gateway URL consumed via ARM.
3. **Microsoft Foundry / Azure AI Services account** (kind `AIServices`, custom subdomain) with **chat deployment** (e.g. `gpt-4o-mini`, GlobalStandard; capacity comfortably above demo needs). `disableLocalAuth` may be true (MI path is default).
4. **Azure AI Content Safety** account (kind `ContentSafety`, custom subdomain), or reuse AIServices if validated.
5. **Log Analytics workspace + Application Insights** (workspace-based; keep local auth enabled for the connection-string logger) with custom metric dimensions enabled (IaC mechanism TBD).
6. Role assignments:
   * APIM MI -> `Cognitive Services OpenAI User` (5e0bd9bd-7b93-4f28-af87-19fc36ad61bd) on Foundry/AOAI.
   * APIM MI -> `Cognitive Services User` (a97b65f3-24c7-4388-baec-2e87135dc908) on Content Safety.
   * CI identity (OIDC SP) -> `API Management Service Contributor` (or Contributor) on APIM/RG for ARM PUTs + `listSecrets`; `Monitoring Reader`/`Log Analytics Reader` on AI/workspace for KQL; plus rights to create role assignments if Bicep assigns roles (User Access Administrator / RBAC Administrator or Owner).
   * Optional: `Monitoring Metrics Publisher` if moving the APIM logger to MI auth.
7. Optional Demo 4 real multi-region: 2 more AOAI/Foundry accounts with identical model+version deployments (same RBAC for APIM MI).
8. Optional: APIM logger + diagnostic could be pre-created in Bicep, but notebooks create/overwrite them anyway.

APIM child resources created by notebooks (Bicep not required; must be removed by teardown):

* APIs: `demo1-openai-api`, `demo2-metering-api`, `demo3-content-safety-api`, `demo4-resilient-pool-api`, `demo4-mock-origin-api` (+ operations, API policies, `applicationinsights` diagnostic on demo2).
* Backends: `demo1-openai-backend`, `demo2-openai-backend`, `demo3-openai-backend`, `demo3-content-safety-backend`, `demo4-ptu-east`, `demo4-ptu-central`, `demo4-payg`, `demo4-aoai-pool`.
* Products: `demo1-token-governance-product`, `demo2-metering`, `demo3-content-safety`, `demo4-resilient-pool`.
* Subscriptions: `demo1-token-governance-sub`, `demo2-metering-sub`, `demo3-content-safety-sub`, `demo4-resilient-pool-sub`, `demo4-mock-origin-sub`.
* Named values: `demo1-tokens-per-minute`, `demo1-daily-token-cap`, `demo{1..4}-aoai-key` (opt), `demo3-content-safety-key` (opt), `demo3-content-safety-blocklist-id` (opt), `demo3-content-safety-threshold-{hate,selfharm,sexual,violence}`, `demo4-mock-fault-{east,central,payg}`, `demo4-mock-retry-after-{east,central,payg}`, `demo4-mock-origin-key`, plus auto `Logger-Credentials--*`.
* Logger: `demo2-application-insights`.

Simplest full teardown = delete the resource group (APIM Basic v2 billing stops). APIM soft-delete retains the name - purge via `az apim deletedservice purge` if re-creating the same name; Cognitive Services accounts are also soft-deleted (`az cognitiveservices account purge`).

## Headless / CI execution of notebooks

* Tooling: `papermill` (add to a CI requirements file) or `jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=900 --output-dir outputs/`. Both need cwd = `notebooks/` (papermill: `--cwd notebooks`; nbconvert executes in the notebook's directory by default). Kernel: `python3` via ipykernel.
* Auth: `azure/login@v2` with OIDC -> `AzureCliCredential` works; set `AZURE_SUBSCRIPTION_ID` explicitly.
* Config: write repo-root `.env` from Bicep outputs before execution, including keys that suppress prompts: `APIM_RESOURCE_GROUP`, `APIM_NAME`, `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT`, `AOAI_KEY=` (empty), `AOAI_API_STYLE=v1`, `APP_INSIGHTS_RESOURCE_ID`, `APP_INSIGHTS_CONNECTION_STRING`, `CONTENT_SAFETY_ENDPOINT`, `CONTENT_SAFETY_KEY=` (empty), `DEMO4_*=` (six empty lines), optional thresholds (e.g. lower `CONTENT_SAFETY_THRESHOLD_VIOLENCE` to trip the mild fixture), `DEMO_RUN` (per-run value).
* Parameters: no `parameters` tag exists. Env/.env drive everything, so papermill `-p` is not needed except for Demo 4 teardown (`REMOVE_WORKSHOP_ARTIFACTS` hardcoded False) - options: add a `parameters`-tagged cell, read it from an env var, or do teardown in a separate script/az CLI step.
* Order: 00 -> demo1 -> demo2 -> demo3 -> demo4 (sequential; shared APIM). Rough runtime: demo1 up to ~4-6 min, demo2 up to ~5 min (ingestion backoff), demo3 ~1 min, demo4 ~4 min (65 s sleep + ~80 calls).
* Failure semantics: most cells only display FAIL/WARNING banners rather than raising; hard raises: Demo 2 cell 21 (RuntimeError if diagnostic/policy missing), Demo 4 cell 5 (unsupported SKU), config validation, ARM errors (`ApimError`). CI assertions on PASS/FAIL need parsing of outputs (e.g. scan executed notebook JSON for "FAIL:" banners) or small code changes.
* Screenshots: charts are inline PNG outputs in executed notebooks; for page screenshots convert to HTML (`nbconvert --to html`) and capture with Playwright, or extract `image/png` outputs from the executed `.ipynb`.
* Data generation for chargeback: Demo 2 traffic (8 calls) is small; a separate traffic-generator script/workflow using the `demo2-metering-sub` key with bounded `x-client-app` values would produce richer `customMetrics`.

## Gaps / risks / questions

1. No IaC or CI exists at all - Bicep, workflows, and teardown are net-new.
2. Interactive prompts (`AOAI_API_STYLE`, `AOAI_KEY`, `CONTENT_SAFETY_KEY`, `DEMO4_*`) fire unless keys are present as lines in `.env` - CI must write `.env` (or code should honor env vars / `interactive=False`).
3. Demo 4 cleanup cell misses products (4), `demo3-content-safety-threshold-*`, `demo3-content-safety-blocklist-id`, logger `demo2-application-insights`, and `Logger-Credentials--*` named values; README claims loggers/products are cleaned.
4. `check_custom_metric_dimensions_enabled` likely never returns PASS (feature name guess); the IaC mechanism to enable "Alerting on custom metric dimensions" on App Insights needs confirmation (open research question).
5. `app_insights_resource_id()` assumes App Insights lives in the APIM resource group when only `APP_INSIGHTS_NAME` is given - prefer passing `APP_INSIGHTS_RESOURCE_ID` from Bicep outputs.
6. Demo 3 mild fixtures may yield NOT TRIPPED; for deterministic CI evidence lower `CONTENT_SAFETY_THRESHOLD_VIOLENCE` (e.g. 2) or accept NOT TRIPPED as non-failing.
7. Demo 4 routing-mode path composition (client operation path appended to mock member URL vs mock operations `/east` etc.) should be verified in the first live run.
8. Models must accept `max_tokens`; avoid reasoning models.
9. 00 notebook `shell=True` with a list is Windows-oriented; on Linux runners it runs bare `az` (passes, prints help banner).
10. `LICENSE` referenced by README badge does not exist.
11. Tests: no pytest config; `python -m unittest discover -s tests -t .` is the reliable command. Presentation-word regex restricts README wording.
12. Region and model/version choices must consider Basic v2 + AIServices + Content Safety (incl. Prompt Shields) regional availability (other research).

## References

* README.md
* requirements.txt
* .env.example
* .gitignore
* shared/config.py, shared/auth.py, shared/apim.py, shared/display.py, shared/fixtures.py
* notebooks/00-setup-and-validation.ipynb, notebooks/demo1-token-limits.ipynb, notebooks/demo2-token-metrics.ipynb, notebooks/demo3-content-safety.ipynb, notebooks/demo4-resilient-pool.ipynb
* policies/demo1-token-limit.xml, policies/demo2-emit-token-metric.xml, policies/demo3-content-safety.xml, policies/demo4-resilient-pool.xml, policies/demo4-mock-origin.xml
* tests/test_apim.py, tests/test_config.py, tests/test_notebooks.py
* docs/ai-governance-flows.svg
* Presentation/Module 8 - Gateway and Metering Plane.pptx
