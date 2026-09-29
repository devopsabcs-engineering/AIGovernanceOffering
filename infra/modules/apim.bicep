metadata description = 'API Management (v2 tier) with a user-assigned identity, the platform Application Insights logger, and a metrics-only service diagnostic.'

@description('Azure region for API Management.')
param location string

@description('API Management service name.')
param apimName string

@description('Publisher email shown in the developer portal.')
param publisherEmail string

@description('Publisher name shown in the developer portal.')
param publisherName string

@description('API Management SKU.')
@allowed([
  'BasicV2'
  'StandardV2'
])
param sku string

@description('API Management scale units.')
@minValue(1)
@maxValue(10)
param skuCount int

@description('Resource ID of the bootstrap-owned user-assigned identity.')
param apimIdentityResourceId string

@description('Client ID of the same user-assigned identity.')
param apimIdentityClientId string

@description('Name of the Application Insights component in this resource group.')
param appInsightsName string

@description('Tags applied to every resource.')
param tags {*: string}

var noBodyCapture = {
  headers: []
  body: {
    bytes: 0
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  tags: tags
  sku: {
    name: sku
    capacity: skuCount
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apimIdentityResourceId}': {}
    }
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    publicNetworkAccess: 'Enabled'
  }
}

// Connection string plus identityClientId: ingestion authenticates with the user-assigned identity (component has DisableLocalAuth).
resource platformLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'apimlogger'
  properties: {
    loggerType: 'applicationInsights'
    description: 'Platform Application Insights logger (managed identity ingestion)'
    resourceId: appInsights.id
    isBuffered: true
    credentials: {
      connectionString: appInsights.properties.ConnectionString
      identityClientId: apimIdentityClientId
    }
  }
}

// The 2024-05-01 diagnostic contract has no LLM message logging block, so no prompt or completion capture is possible here.
resource serviceDiagnostic 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'applicationinsights'
  properties: {
    loggerId: platformLogger.id
    alwaysLog: 'allErrors'
    metrics: true
    logClientIp: false
    httpCorrelationProtocol: 'W3C'
    verbosity: 'information'
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    frontend: {
      request: noBodyCapture
      response: noBodyCapture
    }
    backend: {
      request: noBodyCapture
      response: noBodyCapture
    }
  }
}

output apimId string = apim.id
output apimName string = apim.name
output gatewayUrl string = apim.properties.gatewayUrl
output loggerId string = platformLogger.name
output loggerResourceId string = platformLogger.id
