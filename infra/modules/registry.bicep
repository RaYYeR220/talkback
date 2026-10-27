// Container registry shared by the Container Apps and the Foundry hosted agents.
// The Foundry project pulls hosted-agent images with its managed identity
// through a project connection, as in the azd Foundry synthesizer.

param location string
param tags object
param name string

@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Basic'

param foundryAccountName string
param foundryProjectName string
param foundryProjectPrincipalId string

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
  }
}

resource projectAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, foundryProjectPrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  name: '${foundryAccountName}/${foundryProjectName}'
}

resource acrConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: project
  name: '${name}-conn'
  properties: {
    category: 'ContainerRegistry'
    target: registry.properties.loginServer
    authType: 'ManagedIdentity'
    isSharedToAll: true
    credentials: {
      clientId: foundryProjectPrincipalId
      resourceId: registry.id
    }
    metadata: {
      ResourceId: registry.id
    }
  }
  dependsOn: [
    projectAcrPull
  ]
}

output name string = registry.name
output id string = registry.id
output loginServer string = registry.properties.loginServer
output connectionName string = acrConnection.name
