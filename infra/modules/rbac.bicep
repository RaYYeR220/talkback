// Azure RBAC for the app identities (and the deploying developer).
// AcrPull lives in acr-pull.bicep because the apps need it before they exist.
// Each list holds { principalId, principalType }.

type principal = {
  principalId: string
  principalType: 'User' | 'ServicePrincipal' | 'Group'
}

param foundryAccountName string
param foundryProjectName string
param eventHubNamespaceName string
param storageAccountName string
param generatorJobName string

@description('Foundry User on the account: models via the project endpoint, Content Safety, agent endpoints.')
param foundryUsers principal[] = []

@description('Foundry Agent Consumer on the project: call hosted agents (Responses / A2A).')
param agentConsumers principal[] = []

param eventHubSenders principal[] = []
param eventHubReceivers principal[] = []
param eventHubOwners principal[] = []
param blobContributors principal[] = []
param blobReaders principal[] = []

@description('Container Apps Jobs Operator on the generator job: start a matchday.')
param jobOperators principal[] = []

var roleIds = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  foundryAgentConsumer: 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'
  eventHubsDataSender: '2b629674-e913-4c01-ae53-ef4638d8f975'
  eventHubsDataReceiver: 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
  eventHubsDataOwner: 'f526a384-b230-433a-b45c-95f59c4a2dec'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  containerAppsJobsOperator: 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b'
}

func roleId(id string) string => subscriptionResourceId('Microsoft.Authorization/roleDefinitions', id)

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName

  resource project 'projects' existing = {
    name: foundryProjectName
  }
}

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: eventHubNamespaceName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource generatorJob 'Microsoft.App/jobs@2025-01-01' existing = {
  name: generatorJobName
}

resource foundryUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in foundryUsers: {
    name: guid(account.id, p.principalId, roleIds.foundryUser)
    scope: account
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.foundryUser)
    }
  }
]

resource agentConsumerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in agentConsumers: {
    name: guid(account::project.id, p.principalId, roleIds.foundryAgentConsumer)
    scope: account::project
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.foundryAgentConsumer)
    }
  }
]

resource ehSenderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in eventHubSenders: {
    name: guid(namespace.id, p.principalId, roleIds.eventHubsDataSender)
    scope: namespace
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.eventHubsDataSender)
    }
  }
]

resource ehReceiverAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in eventHubReceivers: {
    name: guid(namespace.id, p.principalId, roleIds.eventHubsDataReceiver)
    scope: namespace
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.eventHubsDataReceiver)
    }
  }
]

resource ehOwnerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in eventHubOwners: {
    name: guid(namespace.id, p.principalId, roleIds.eventHubsDataOwner)
    scope: namespace
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.eventHubsDataOwner)
    }
  }
]

resource blobContributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in blobContributors: {
    name: guid(storage.id, p.principalId, roleIds.storageBlobDataContributor)
    scope: storage
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.storageBlobDataContributor)
    }
  }
]

resource blobReaderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in blobReaders: {
    name: guid(storage.id, p.principalId, roleIds.storageBlobDataReader)
    scope: storage
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.storageBlobDataReader)
    }
  }
]

resource jobOperatorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in jobOperators: {
    name: guid(generatorJob.id, p.principalId, roleIds.containerAppsJobsOperator)
    scope: generatorJob
    properties: {
      principalId: p.principalId
      principalType: p.principalType
      roleDefinitionId: roleId(roleIds.containerAppsJobsOperator)
    }
  }
]
