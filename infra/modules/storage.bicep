// Blob storage: recorded runs (replays), Lab snapshots, Event Hubs checkpoints.
// Shared keys are off; everything goes through Entra ID.

param location string
param tags object
param name string
param containerNames array = [
  'runs'
  'snapshots'
  'checkpoints'
]

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for c in containerNames: {
    parent: blobService
    name: c
    properties: {
      publicAccess: 'None'
    }
  }
]

output name string = account.name
output id string = account.id
output blobEndpoint string = account.properties.primaryEndpoints.blob
