// Cosmos DB (NoSQL): the claim ledger and run records.
// Free tier: 1000 RU/s shared at database level + 25 GB at no cost (one free
// account per subscription). Without free tier the account goes serverless.
// Data plane is Entra-only; principals get the built-in data roles.

param location string
param tags object
param accountName string
param databaseName string = 'talkback'
param freeTier bool = true

@description('Principal IDs that read and write data.')
param dataContributorPrincipalIds array = []

@description('Principal IDs that only read data.')
param dataReaderPrincipalIds array = []

// Every ledger document carries run_id, so one broadcast is one logical
// partition. MAF CosmosCheckpointStorage expects /workflow_name.
var containers = [
  { name: 'cues', partitionKey: '/run_id' }
  { name: 'claims', partitionKey: '/run_id' }
  { name: 'verdicts', partitionKey: '/run_id' }
  { name: 'runs', partitionKey: '/run_id' }
  { name: 'checkpoints', partitionKey: '/workflow_name' }
]

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: freeTier
    capabilities: freeTier ? [] : [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: freeTier ? { throughput: 1000 } : {}
  }
}

resource sqlContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for c in containers: {
    parent: database
    name: c.name
    properties: {
      resource: {
        id: c.name
        partitionKey: {
          paths: [
            c.partitionKey
          ]
          kind: 'Hash'
          version: 2
        }
      }
    }
  }
]

// Built-in data-plane roles: ...0001 Data Reader, ...0002 Data Contributor.
// One at a time: Cosmos rejects concurrent role-assignment writes.
@batchSize(1)
resource contributorAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for p in dataContributorPrincipalIds: {
    parent: account
    name: guid(account.id, p, 'data-contributor')
    properties: {
      principalId: p
      roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
      scope: account.id
    }
  }
]

@batchSize(1)
resource readerAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for p in dataReaderPrincipalIds: {
    parent: account
    name: guid(account.id, p, 'data-reader')
    properties: {
      principalId: p
      roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001'
      scope: account.id
    }
    dependsOn: [
      contributorAssignments
    ]
  }
]

output name string = account.name
output endpoint string = account.properties.documentEndpoint
output databaseName string = database.name
