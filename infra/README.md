# Lab infrastructure

Resource-group-scoped Bicep for the AI Governance lab platform. The lab session automation deploys it; an administrator runs [scripts/bootstrap-lab.ps1](../scripts/bootstrap-lab.ps1) once beforehand.

## What it deploys

| Module | Resources |
| --- | --- |
| [modules/monitoring.bicep](modules/monitoring.bicep) | Log Analytics workspace, workspace-based Application Insights (local auth disabled, custom metric dimensions opted in) |
| [modules/ai.bicep](modules/ai.bicep) | Model account with one chat deployment, Content Safety account (both Entra-only) |
| [modules/apim.bicep](modules/apim.bicep) | API Management `BasicV2` with the bootstrap user-assigned identity, logger `apimlogger`, metrics-only service diagnostic |
| [modules/platform-api.bicep](modules/platform-api.bicep) | API `ai-gateway-api`, backend `ai-gateway-foundry`, products and subscriptions for `team-retail`, `team-finance`, `team-hr` |

Policies come from [policies/platform-ai-gateway.xml](../policies/platform-ai-gateway.xml) and [policies/platform-team-product.xml](../policies/platform-team-product.xml).

## Parameters

[main.bicepparam](main.bicepparam) reads every approval-bound value from an environment variable with no default. Until those variables exist, `az bicep build-params` and deployment fail with `BCP427`, so no model, region, or identity is guessed.

| Environment variable | Source |
| --- | --- |
| `AIGOV_NAME_SUFFIX`, `AIGOV_LOCATION`, `AIGOV_APIM_IDENTITY_RESOURCE_ID`, `AIGOV_APIM_IDENTITY_CLIENT_ID` | Repository variables set by the bootstrap script |
| `AIGOV_GENERATION`, `AIGOV_AI_LOCATION`, `AIGOV_CONTENT_SAFETY_LOCATION`, `AIGOV_PUBLISHER_EMAIL` | Approved during environment setup |
| `AIGOV_CHAT_MODEL_NAME`, `AIGOV_CHAT_MODEL_VERSION`, `AIGOV_CHAT_DEPLOYMENT_SKU`, `AIGOV_CHAT_DEPLOYMENT_CAPACITY` | Approved model tuple |
| `AIGOV_ALLOW_GLOBAL_PROCESSING` | Optional, defaults to `false` |
| `AIGOV_ENVIRONMENT_NAME`, `AIGOV_PUBLISHER_NAME` | Optional, default to `lab` and `AI Governance Lab` |

With `allowGlobalProcessing=false`, a `Global*` or `DataZone*` deployment SKU stops the deployment during template validation through `fail()`.

## Resource names

Names are deterministic: `<abbr>-aigov-<environmentName>-<generation>-<instanceNumber>`, plus `-<nameSuffix>` for globally unique names.

| Resource | Pattern | Example |
| --- | --- | --- |
| Log Analytics | `log-aigov-<env>-<gen>-<inst>` | `log-aigov-lab-g01-001` |
| Application Insights | `appi-aigov-<env>-<gen>-<inst>` | `appi-aigov-lab-g01-001` |
| API Management | `apim-aigov-<env>-<gen>-<inst>-<suffix>` | `apim-aigov-lab-g01-001-953a2c` |
| Model account | `aif-aigov-<env>-<gen>-<inst>-<suffix>` | `aif-aigov-lab-g01-001-953a2c` |
| Content Safety | `cs-aigov-<env>-<gen>-<inst>-<suffix>` | `cs-aigov-lab-g01-001-953a2c` |
| Chat deployment | `chat` | `chat` |
| Module deployments | `aigov-main-<gen>-<module>` | `aigov-main-g01-apim` |

## Local validation

```powershell
az bicep build --file infra/main.bicep
az bicep lint --file infra/main.bicep
python -m unittest discover -s tests -p "test_infra.py"
```
