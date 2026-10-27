// One user-assigned identity per workload. Created before the apps so role
// assignments (AcrPull first) exist by the time a revision starts.

param location string
param tags object
param resourceToken string

resource talkback 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-talkback-${resourceToken}'
  location: location
  tags: tags
}

resource generator 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-generator-${resourceToken}'
  location: location
  tags: tags
}

resource web 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-web-${resourceToken}'
  location: location
  tags: tags
}

resource mcp 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mcp-${resourceToken}'
  location: location
  tags: tags
}

// Plan B only: Archivist and Lab as Container Apps.
resource agents 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-agents-${resourceToken}'
  location: location
  tags: tags
}

output talkback object = { id: talkback.id, principalId: talkback.properties.principalId, clientId: talkback.properties.clientId }
output generator object = { id: generator.id, principalId: generator.properties.principalId, clientId: generator.properties.clientId }
output web object = { id: web.id, principalId: web.properties.principalId, clientId: web.properties.clientId }
output mcp object = { id: mcp.id, principalId: mcp.properties.principalId, clientId: mcp.properties.clientId }
output agents object = { id: agents.id, principalId: agents.properties.principalId, clientId: agents.properties.clientId }
