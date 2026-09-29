metadata description = 'Platform AI gateway API, model backend, per-team products with token limits, and team subscriptions.'

@export()
@description('One team product with its own subscription, token rate limit, and daily token quota.')
type teamConfig = {
  @description('Product ID, also the subscription ID prefix, for example team-retail.')
  name: string

  @description('Display name of the product.')
  displayName: string

  @description('Tokens per minute for each subscription of this product.')
  @minValue(1)
  tokensPerMinute: int

  @description('Daily token quota for each subscription of this product.')
  @minValue(1)
  dailyTokenQuota: int
}

@description('Existing API Management service name.')
param apimName string

@description('Model backend base URL, ending in /openai.')
param backendUrl string

@description('Client ID of the APIM user-assigned identity, stored in a non-secret named value used by the API policy.')
param apimIdentityClientId string

@description('Team products to create.')
@minLength(1)
param teams teamConfig[]

var apiId = 'ai-gateway-api'
var productPolicyTemplate = loadTextContent('../../policies/platform-team-product.xml')

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource identityClientIdNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-gateway-identity-client-id'
  properties: {
    displayName: 'ai-gateway-identity-client-id'
    value: apimIdentityClientId
    secret: false
  }
}

resource backend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-gateway-foundry'
  properties: {
    url: backendUrl
    protocol: 'http'
    description: 'Platform model backend; authenticated by the API policy with the user-assigned identity'
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: apiId
  properties: {
    displayName: 'AI Gateway (platform)'
    path: 'ai-gateway'
    protocols: [
      'https'
    ]
    subscriptionRequired: true
    subscriptionKeyParameterNames: {
      header: 'Ocp-Apim-Subscription-Key'
      query: 'subscription-key'
    }
  }
}

resource chatCompletionsV1 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'chat-completions-v1'
  properties: {
    displayName: 'Chat completions (v1)'
    method: 'POST'
    urlTemplate: '/v1/chat/completions'
  }
}

resource chatCompletionsClassic 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'chat-completions-classic'
  properties: {
    displayName: 'Chat completions (deployment path)'
    method: 'POST'
    urlTemplate: '/deployments/{deployment-id}/chat/completions'
    templateParameters: [
      {
        name: 'deployment-id'
        type: 'string'
        required: true
      }
    ]
  }
}

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../../policies/platform-ai-gateway.xml')
  }
  dependsOn: [
    backend
    identityClientIdNamedValue
  ]
}

resource products 'Microsoft.ApiManagement/service/products@2024-05-01' = [
  for team in teams: {
    parent: apim
    name: team.name
    properties: {
      displayName: team.displayName
      description: '${team.displayName}: ${team.tokensPerMinute} tokens per minute, ${team.dailyTokenQuota} tokens per day'
      subscriptionRequired: true
      approvalRequired: false
      subscriptionsLimit: 1
      state: 'published'
    }
  }
]

resource productApis 'Microsoft.ApiManagement/service/products/apis@2024-05-01' = [
  for (team, i) in teams: {
    parent: products[i]
    name: api.name
  }
]

resource productPolicies 'Microsoft.ApiManagement/service/products/policies@2024-05-01' = [
  for (team, i) in teams: {
    parent: products[i]
    name: 'policy'
    properties: {
      format: 'rawxml'
      value: replace(
        replace(productPolicyTemplate, '__TOKENS_PER_MINUTE__', string(team.tokensPerMinute)),
        '__DAILY_TOKEN_QUOTA__',
        string(team.dailyTokenQuota)
      )
    }
  }
]

resource teamSubscriptions 'Microsoft.ApiManagement/service/subscriptions@2024-05-01' = [
  for (team, i) in teams: {
    parent: apim
    name: '${team.name}-sub'
    properties: {
      displayName: '${team.displayName} subscription'
      scope: products[i].id
      state: 'active'
      allowTracing: false
    }
  }
]

output apiId string = api.name
output apiPath string = api.properties.path
output backendId string = backend.name
output identityClientIdNamedValueId string = identityClientIdNamedValue.name
output productIds string[] = [for (team, i) in teams: products[i].name]
output subscriptionIds string[] = [for (team, i) in teams: teamSubscriptions[i].name]
