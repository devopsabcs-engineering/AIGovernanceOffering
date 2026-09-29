using './main.bicep'

// Every approval-bound value is read from an environment variable with no default.
// Until the Phase 6 decisions set these variables (repository variables in CI,
// or the operator shell locally), `az bicep build-params` and any deployment fail
// with "environment variable ... does not exist", so no model, region, or
// identity is ever guessed from source control.

param environmentName = readEnvironmentVariable('AIGOV_ENVIRONMENT_NAME', 'lab')
param instanceNumber = '001'
param generation = readEnvironmentVariable('AIGOV_GENERATION')
param nameSuffix = readEnvironmentVariable('AIGOV_NAME_SUFFIX')

param location = readEnvironmentVariable('AIGOV_LOCATION')
param aiLocation = readEnvironmentVariable('AIGOV_AI_LOCATION')
param contentSafetyLocation = readEnvironmentVariable('AIGOV_CONTENT_SAFETY_LOCATION')

param publisherEmail = readEnvironmentVariable('AIGOV_PUBLISHER_EMAIL')
param publisherName = readEnvironmentVariable('AIGOV_PUBLISHER_NAME', 'AI Governance Lab')
param sku = 'BasicV2'
param skuCount = 1

param apimIdentityResourceId = readEnvironmentVariable('AIGOV_APIM_IDENTITY_RESOURCE_ID')
param apimIdentityClientId = readEnvironmentVariable('AIGOV_APIM_IDENTITY_CLIENT_ID')

param chatModelName = readEnvironmentVariable('AIGOV_CHAT_MODEL_NAME')
param chatModelVersion = readEnvironmentVariable('AIGOV_CHAT_MODEL_VERSION')
param chatDeploymentSku = readEnvironmentVariable('AIGOV_CHAT_DEPLOYMENT_SKU')
param chatDeploymentCapacity = int(readEnvironmentVariable('AIGOV_CHAT_DEPLOYMENT_CAPACITY'))
param allowGlobalProcessing = bool(readEnvironmentVariable('AIGOV_ALLOW_GLOBAL_PROCESSING', 'false'))
