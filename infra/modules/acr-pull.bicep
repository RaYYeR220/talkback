// AcrPull for the app identities, granted before the apps are created.

param registryName string
param principalIds array

var acrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource assignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in principalIds: {
    name: guid(registry.id, p, acrPull)
    scope: registry
    properties: {
      principalId: p
      principalType: 'ServicePrincipal'
      roleDefinitionId: acrPull
    }
  }
]
