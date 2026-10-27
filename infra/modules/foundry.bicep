// Microsoft Foundry: AIServices account (models + Content Safety on one endpoint),
// a project, model deployments and the project's App Insights connection
// (Foundry tracing; hosted agents get the connection string injected).
//
// Shape follows the azd Foundry synthesizer (azure.ai.projects extension
// templates/modules/resources.bicep), so `azd deploy` of azure.ai.agent
// services finds what it expects.

type modelDeployment = {
  name: string
  model: {
    format: string
    name: string
    version: string
  }
  sku: {
    name: string
    capacity: int
  }
}

param location string
param tags object
param accountName string
param projectName string
param deployments modelDeployment[]

param appInsightsId string
@secure()
param appInsightsConnectionString string
param workspaceName string

@description('Deploying user or principal; gets Foundry User on the project. Empty skips it.')
param principalId string = ''
param principalType string = 'User'

var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  logAnalyticsDataReader: '3b03c2da-16b3-4a49-8834-0f8130efdd3b'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
  }

  // ARM throttles concurrent deployments on one account.
  @batchSize(1)
  resource modelDeployments 'deployments' = [
    for d in deployments: {
      name: d.name
      sku: d.sku
      properties: {
        model: d.model
        versionUpgradeOption: 'NoAutoUpgrade'
      }
    }
  ]

  resource project 'projects' = {
    name: projectName
    location: location
    tags: tags
    identity: {
      type: 'SystemAssigned'
    }
    properties: {
      displayName: projectName
      description: 'Talkback editorial gallery'
    }
    dependsOn: [
      modelDeployments
    ]
  }
}

// The connection type takes the preview API version (GA 2025-06-01 misses the connections sub-resource); its
// parent is the project declared above. A second, `existing` declaration of the project would make ARM see the
// same resource defined twice.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: account::project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsightsId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appInsightsConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsightsId
    }
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

// Evaluations read traces from the workspace with the project identity.
resource projectLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, account::project.id, roles.logAnalyticsDataReader)
  scope: workspace
  properties: {
    principalId: account::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsDataReader)
  }
}

// Project scope on purpose: the platform may add an account-scope Foundry User
// for the creator itself, and a duplicate assignment would fail the deployment.
resource developerFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(account::project.id, principalId, roles.foundryUser)
  scope: account::project
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

output accountName string = account.name
output accountId string = account.id
output accountEndpoint string = account.properties.endpoint
output projectName string = account::project.name
output projectId string = account::project.id
output projectPrincipalId string = account::project.identity.principalId
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${account::project.name}'
output openAiEndpoint string = 'https://${account.name}.openai.azure.com/'
