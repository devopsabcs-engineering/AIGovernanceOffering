metadata description = 'Model account with one chat deployment and a Content Safety account, both Entra-only (local keys disabled).'

@description('Azure region for the model account and deployment.')
param aiLocation string

@description('Azure region for the Content Safety account.')
param contentSafetyLocation string

@description('Model account name; also used as the custom subdomain.')
param modelAccountName string

@description('Content Safety account name; also used as the custom subdomain.')
param contentSafetyName string

@description('Chat deployment name.')
param chatDeploymentName string

@description('Approved chat model name.')
param chatModelName string

@description('Approved chat model version.')
param chatModelVersion string

@description('Approved deployment SKU (already checked against allowGlobalProcessing by main.bicep).')
param chatDeploymentSku string

@description('Approved deployment capacity in capacity units.')
@minValue(1)
param chatDeploymentCapacity int

@description('Tags applied to every resource.')
param tags {*: string}

resource modelAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: modelAccountName
  location: aiLocation
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  tags: tags
  properties: {
    customSubDomainName: modelAccountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: modelAccount
  name: chatDeploymentName
  sku: {
    name: chatDeploymentSku
    capacity: chatDeploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource contentSafety 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: contentSafetyName
  location: contentSafetyLocation
  kind: 'ContentSafety'
  sku: {
    name: 'S0'
  }
  tags: tags
  properties: {
    customSubDomainName: contentSafetyName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

output modelAccountId string = modelAccount.id
output modelAccountName string = modelAccount.name
@description('Resource root with no path and no trailing slash, matching the AOAI_ENDPOINT contract.')
output openAiEndpoint string = 'https://${modelAccount.properties.customSubDomainName}.openai.azure.com'
output chatDeploymentName string = chatDeployment.name
output contentSafetyId string = contentSafety.id
output contentSafetyName string = contentSafety.name
output contentSafetyEndpoint string = contentSafety.properties.endpoint
