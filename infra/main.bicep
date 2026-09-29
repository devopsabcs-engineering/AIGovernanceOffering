metadata description = 'AI Governance lab platform (resource group scope): API Management v2 AI gateway, model and Content Safety accounts, and monitoring.'

targetScope = 'resourceGroup'

import { teamConfig } from 'modules/platform-api.bicep'

@description('Short environment name used in resource names (LZA-aligned).')
@minLength(2)
@maxLength(8)
param environmentName string = 'lab'

@description('Three-digit instance number used in resource names (LZA-aligned).')
@minLength(3)
@maxLength(3)
param instanceNumber string = '001'

@description('Ownership generation, for example g01. Use a new generation when tombstones of a previous generation block name reuse.')
@minLength(2)
@maxLength(4)
param generation string

@description('Deterministic suffix for globally unique names; the bootstrap script sets it once as AIGOV_NAME_SUFFIX.')
@minLength(4)
@maxLength(6)
param nameSuffix string

@description('Azure region for API Management and monitoring resources.')
param location string = resourceGroup().location

@description('Approved Azure region for the model account and chat deployment.')
param aiLocation string

@description('Approved Azure region for the Content Safety account.')
param contentSafetyLocation string = aiLocation

@description('API Management publisher email.')
param publisherEmail string

@description('API Management publisher name.')
param publisherName string

@description('API Management SKU (LZA-aligned).')
@allowed([
  'BasicV2'
  'StandardV2'
])
param sku string = 'BasicV2'

@description('API Management scale units (LZA-aligned).')
@minValue(1)
@maxValue(10)
param skuCount int = 1

@description('Resource ID of the bootstrap-owned user-assigned identity (identity resource group).')
param apimIdentityResourceId string

@description('Client ID of the same user-assigned identity.')
param apimIdentityClientId string

@description('Approved chat model name.')
param chatModelName string

@description('Approved chat model version.')
param chatModelVersion string

@description('Approved chat deployment SKU, for example Standard. Global and DataZone SKUs require allowGlobalProcessing.')
param chatDeploymentSku string

@description('Approved chat deployment capacity in capacity units.')
@minValue(1)
param chatDeploymentCapacity int

@description('Allow deployment SKUs that may process data outside the model account region (Global*, DataZone*).')
param allowGlobalProcessing bool = false

@description('Team products, each with its own subscription, token rate limit, and daily token quota.')
@minLength(1)
param teams teamConfig[] = [
  {
    name: 'team-retail'
    displayName: 'Team Retail'
    tokensPerMinute: 3000
    dailyTokenQuota: 30000
  }
  {
    name: 'team-finance'
    displayName: 'Team Finance'
    tokensPerMinute: 2000
    dailyTokenQuota: 20000
  }
  {
    name: 'team-hr'
    displayName: 'Team HR'
    tokensPerMinute: 1000
    dailyTokenQuota: 10000
  }
]

var tokenMetricNamespace = 'aigov'
var clientAppAllowlist = [
  'retail-web'
  'finance-batch'
  'hr-assistant'
]

var nameToken = 'aigov-${environmentName}-${generation}-${instanceNumber}'
var names = {
  logAnalytics: 'log-${nameToken}'
  appInsights: 'appi-${nameToken}'
  apim: 'apim-${nameToken}-${nameSuffix}'
  modelAccount: 'aif-${nameToken}-${nameSuffix}'
  contentSafety: 'cs-${nameToken}-${nameSuffix}'
  chatDeployment: 'chat'
}

var tags = {
  'aigov-owner': 'aigov-lab'
  'aigov-environment': environmentName
  'aigov-generation': generation
}

var crossRegionSku = startsWith(toLower(chatDeploymentSku), 'global') || startsWith(toLower(chatDeploymentSku), 'datazone')
var approvedChatDeploymentSku = crossRegionSku && !allowGlobalProcessing
  ? fail('chatDeploymentSku "${chatDeploymentSku}" can process data outside ${aiLocation}; set allowGlobalProcessing=true only after that is approved.')
  : chatDeploymentSku

// Deterministic module deployment names let lab_session prune this generation's nested deployment records.
module monitoring 'modules/monitoring.bicep' = {
  name: 'aigov-main-${generation}-monitoring'
  params: {
    location: location
    logAnalyticsName: names.logAnalytics
    appInsightsName: names.appInsights
    tags: tags
  }
}

module ai 'modules/ai.bicep' = {
  name: 'aigov-main-${generation}-ai'
  params: {
    aiLocation: aiLocation
    contentSafetyLocation: contentSafetyLocation
    modelAccountName: names.modelAccount
    contentSafetyName: names.contentSafety
    chatDeploymentName: names.chatDeployment
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatDeploymentSku: approvedChatDeploymentSku
    chatDeploymentCapacity: chatDeploymentCapacity
    tags: tags
  }
}

module apim 'modules/apim.bicep' = {
  name: 'aigov-main-${generation}-apim'
  params: {
    location: location
    apimName: names.apim
    publisherEmail: publisherEmail
    publisherName: publisherName
    sku: sku
    skuCount: skuCount
    apimIdentityResourceId: apimIdentityResourceId
    apimIdentityClientId: apimIdentityClientId
    appInsightsName: monitoring.outputs.appInsightsName
    tags: tags
  }
}

module platformApi 'modules/platform-api.bicep' = {
  name: 'aigov-main-${generation}-platform-api'
  params: {
    apimName: apim.outputs.apimName
    backendUrl: '${ai.outputs.openAiEndpoint}/openai'
    apimIdentityClientId: apimIdentityClientId
    teams: teams
  }
}

output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
output AZURE_RESOURCE_GROUP string = resourceGroup().name
output GENERATION string = generation
output APIM_NAME string = apim.outputs.apimName
output APIM_RESOURCE_ID string = apim.outputs.apimId
output APIM_GATEWAY_URL string = apim.outputs.gatewayUrl
output APIM_IDENTITY_CLIENT_ID string = apimIdentityClientId
output APIM_IDENTITY_RESOURCE_ID string = apimIdentityResourceId
output AOAI_ACCOUNT_NAME string = ai.outputs.modelAccountName
output AOAI_ACCOUNT_RESOURCE_ID string = ai.outputs.modelAccountId
output AOAI_ENDPOINT string = ai.outputs.openAiEndpoint
output AOAI_DEPLOYMENT string = ai.outputs.chatDeploymentName
output AOAI_API_STYLE string = 'v1'
output CONTENT_SAFETY_NAME string = ai.outputs.contentSafetyName
output CONTENT_SAFETY_RESOURCE_ID string = ai.outputs.contentSafetyId
output CONTENT_SAFETY_ENDPOINT string = ai.outputs.contentSafetyEndpoint
output APP_INSIGHTS_NAME string = monitoring.outputs.appInsightsName
output APP_INSIGHTS_RESOURCE_ID string = monitoring.outputs.appInsightsId
output LOG_ANALYTICS_WORKSPACE_NAME string = monitoring.outputs.workspaceName
output LOG_ANALYTICS_WORKSPACE_RESOURCE_ID string = monitoring.outputs.workspaceId
output LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID string = monitoring.outputs.workspaceCustomerId
output PLATFORM_LOGGER_ID string = apim.outputs.loggerId
output PLATFORM_API_ID string = platformApi.outputs.apiId
output PLATFORM_API_PATH string = platformApi.outputs.apiPath
output PLATFORM_BACKEND_ID string = platformApi.outputs.backendId
output TOKEN_METRIC_NAMESPACE string = tokenMetricNamespace
output CLIENT_APP_ALLOWLIST string[] = clientAppAllowlist
output TEAM_PRODUCT_IDS string[] = platformApi.outputs.productIds
output TEAM_SUBSCRIPTION_IDS string[] = platformApi.outputs.subscriptionIds
