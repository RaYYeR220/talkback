// Talkback on Azure: Foundry (models, hosted agents, tracing), Event Hubs,
// Container Apps, Cosmos DB, Blob storage, monitoring and a cost budget.
// Provisioned by `azd provision`; images and agent versions ship with `azd deploy`.

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd environment name; drives the resource group and resource token.')
param environmentName string

@minLength(1)
@description('Region for everything. Needs Foundry hosted agents and the chosen models (Global Standard).')
param location string

@description('Resource group name. Empty means rg-<environmentName>.')
param resourceGroupName string = ''

@description('Deploying user (azd sets AZURE_PRINCIPAL_ID). Gets data-plane access for local runs.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

// Models (Global Standard). Deployment name = model name.
param fastModelName string = 'gpt-5.4-mini'
param fastModelVersion string = '2026-03-17'
@description('Thousands of tokens per minute.')
param fastModelCapacity int = 50
param strongModelName string = 'gpt-6.1-sol'
param strongModelVersion string = '2026-09-29'
@description('Thousands of tokens per minute.')
param strongModelCapacity int = 50
param modelSkuName string = 'GlobalStandard'
@description('Reasoning effort for the strong model when it is a reasoning model (gpt-5, o-series); empty for one that is not.')
param strongReasoningEffort string = 'low'
@description('false provisions everything but the model deployments (a subscription without model quota yet); the gallery then serves its recorded replay only.')
param deployModels bool = true

// Hosted agents (azure.ai.agent services in azure.yaml). Names must match there.
param archivistAgentName string = 'talkback-archivist'
param labAgentName string = 'talkback-lab'

@description('Plan B: run Archivist and Lab as internal Container Apps serving A2A v1.0 instead of Foundry hosted agents.')
param agentsOnAca bool = false

@description('Grant Foundry Agent Consumer on the project (least privilege for A2A). Foundry User on the account already covers agent endpoints, so this can be turned off if the role is not available in the tenant yet.')
param assignAgentConsumerRole bool = true

// Sizing
param talkbackCpu string = '1.0'
param talkbackMemory string = '2Gi'
param talkbackMinReplicas int = 1
@description('Keep 1 until the service shares matchday state across replicas; KEDA then scales up to the partition count.')
param talkbackMaxReplicas int = 1
param webMinReplicas int = 1

// Data
@description('Cosmos DB free tier (one per subscription). false switches the account to serverless.')
param cosmosFreeTier bool = true
@allowed(['Basic', 'Standard'])
param eventHubSku string = 'Standard'
@description('Log Analytics daily ingestion cap in GB.')
param logDailyCapGb string = '0.5'

// Budget
param budgetAmount int = 60
@description('Where budget alerts go (azd env set BUDGET_CONTACT_EMAIL ...). Empty skips the budget; see the BUDGET_NAME output.')
param budgetContactEmail string = ''
param budgetMonth string = utcNow('yyyy-MM')

// Set by azd (SERVICE_<NAME>_RESOURCE_EXISTS) so re-provisioning keeps deployed images.
param talkbackExists bool = false
param generatorExists bool = false
param webExists bool = false
param mcpExists bool = false
param archivistAcaExists bool = false
param labAcaExists bool = false

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  project: 'talkback'
}
var rgName = empty(resourceGroupName) ? 'rg-${environmentName}' : resourceGroupName

var names = {
  workspace: 'log-${resourceToken}'
  appInsights: 'appi-${resourceToken}'
  foundry: 'aif-${resourceToken}'
  project: 'talkback'
  registry: 'cr${resourceToken}'
  eventHubs: 'evhns-${resourceToken}'
  storage: 'st${resourceToken}'
  cosmos: 'cosmos-${resourceToken}'
  environment: 'cae-${resourceToken}'
  talkback: 'talkback'
  web: 'talkback-web'
  mcp: 'talkback-mcp'
  generator: 'talkback-generator'
  archivistAca: 'archivist'
  labAca: 'lab'
}

var deployments = [
  {
    name: fastModelName
    model: { format: 'OpenAI', name: fastModelName, version: fastModelVersion }
    sku: { name: modelSkuName, capacity: fastModelCapacity }
  }
  {
    name: strongModelName
    model: { format: 'OpenAI', name: strongModelName, version: strongModelVersion }
    sku: { name: modelSkuName, capacity: strongModelCapacity }
  }
]

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    tags: tags
    workspaceName: names.workspace
    appInsightsName: names.appInsights
    dailyCapGb: logDailyCapGb
  }
}

module foundry 'modules/foundry.bicep' = {
  scope: rg
  name: 'foundry'
  params: {
    location: location
    tags: tags
    accountName: names.foundry
    projectName: names.project
    deployments: deployModels ? deployments : []
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.connectionString
    workspaceName: monitoring.outputs.workspaceName
    principalId: principalId
    principalType: principalType
  }
}

module registry 'modules/registry.bicep' = {
  scope: rg
  name: 'registry'
  params: {
    location: location
    tags: tags
    name: names.registry
    foundryAccountName: foundry.outputs.accountName
    foundryProjectName: foundry.outputs.projectName
    foundryProjectPrincipalId: foundry.outputs.projectPrincipalId
  }
}

module eventHubs 'modules/eventhubs.bicep' = {
  scope: rg
  name: 'eventhubs'
  params: {
    location: location
    tags: tags
    namespaceName: names.eventHubs
    sku: eventHubSku
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    tags: tags
    name: names.storage
  }
}

module identities 'modules/identities.bicep' = {
  scope: rg
  name: 'identities'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
  }
}

module acrPull 'modules/acr-pull.bicep' = {
  scope: rg
  name: 'acr-pull'
  params: {
    registryName: registry.outputs.name
    principalIds: [
      identities.outputs.talkback.principalId
      identities.outputs.generator.principalId
      identities.outputs.web.principalId
      identities.outputs.mcp.principalId
      identities.outputs.agents.principalId
    ]
  }
}

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    location: location
    tags: tags
    accountName: names.cosmos
    freeTier: cosmosFreeTier
    dataContributorPrincipalIds: concat(
      [
        identities.outputs.talkback.principalId
        identities.outputs.generator.principalId
      ],
      empty(principalId) ? [] : [principalId]
    )
    dataReaderPrincipalIds: [
      identities.outputs.mcp.principalId
    ]
  }
}

module environment 'modules/aca-environment.bicep' = {
  scope: rg
  name: 'aca-environment'
  params: {
    location: location
    tags: tags
    name: names.environment
    workspaceName: monitoring.outputs.workspaceName
  }
}

// Endpoints the apps need, computed up front so nothing is circular.
var webUrl = 'https://${names.web}.${environment.outputs.defaultDomain}'
var talkbackUrl = 'https://${names.talkback}.${environment.outputs.defaultDomain}'
var archivistA2aUrl = agentsOnAca
  ? 'https://${names.archivistAca}.internal.${environment.outputs.defaultDomain}'
  : '${foundry.outputs.projectEndpoint}/agents/${archivistAgentName}/endpoint/protocols/a2a'
var labA2aUrl = agentsOnAca
  ? 'https://${names.labAca}.internal.${environment.outputs.defaultDomain}'
  : '${foundry.outputs.projectEndpoint}/agents/${labAgentName}/endpoint/protocols/a2a'
var agentCardPath = agentsOnAca ? '.well-known/agent-card.json' : 'agentCard/v1.0'
// Foundry's A2A gateway serves prompt agents only; the gallery calls the hosted agents on their Responses endpoint.
var archivistResponsesUrl = agentsOnAca
  ? ''
  : '${foundry.outputs.projectEndpoint}/agents/${archivistAgentName}/endpoint/protocols/openai/responses?api-version=v1'
var labResponsesUrl = agentsOnAca
  ? ''
  : '${foundry.outputs.projectEndpoint}/agents/${labAgentName}/endpoint/protocols/openai/responses?api-version=v1'

var telemetryEnv = [
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
]
var foundryEnv = [
  { name: 'TALKBACK_LLM', value: 'foundry' }
  { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundry.outputs.projectEndpoint }
  { name: 'FOUNDRY_MODEL_FAST', value: fastModelName }
  { name: 'FOUNDRY_MODEL_STRONG', value: strongModelName }
  { name: 'TALKBACK_REASONING_EFFORT_STRONG', value: strongReasoningEffort }
  { name: 'CONTENT_SAFETY_ENDPOINT', value: foundry.outputs.accountEndpoint }
]
var eventHubEnv = [
  { name: 'EVENTHUB_FQDN', value: eventHubs.outputs.fqdn }
  { name: 'EVENTHUB_NAME', value: eventHubs.outputs.hubName }
  { name: 'EVENTHUB_CONSUMER_GROUP', value: eventHubs.outputs.consumerGroupName }
]
var dataEnv = [
  { name: 'STORAGE_ACCOUNT_URL', value: storage.outputs.blobEndpoint }
  { name: 'STORAGE_CONTAINER_RUNS', value: 'runs' }
  { name: 'STORAGE_CONTAINER_SNAPSHOTS', value: 'snapshots' }
  { name: 'STORAGE_CONTAINER_CHECKPOINTS', value: 'checkpoints' }
  { name: 'COSMOS_ENDPOINT', value: cosmos.outputs.endpoint }
  { name: 'COSMOS_DATABASE', value: cosmos.outputs.databaseName }
  // MAF CosmosCheckpointStorage reads these.
  { name: 'AZURE_COSMOS_ENDPOINT', value: cosmos.outputs.endpoint }
  { name: 'AZURE_COSMOS_DATABASE_NAME', value: cosmos.outputs.databaseName }
  { name: 'AZURE_COSMOS_CONTAINER_NAME', value: 'checkpoints' }
]

module generator 'modules/container-job.bicep' = {
  scope: rg
  name: 'generator'
  params: {
    location: location
    tags: tags
    name: names.generator
    serviceName: 'generator'
    environmentId: environment.outputs.id
    identityId: identities.outputs.generator.id
    registryServer: registry.outputs.loginServer
    exists: generatorExists
    cpu: '1.0'
    memory: '2Gi'
    appInsightsConnectionString: monitoring.outputs.connectionString
    env: concat(telemetryEnv, eventHubEnv, dataEnv, [
      { name: 'AZURE_CLIENT_ID', value: identities.outputs.generator.clientId }
      { name: 'OTEL_SERVICE_NAME', value: 'generator' }
    ])
  }
  dependsOn: [
    acrPull
  ]
}

module talkback 'modules/container-app.bicep' = {
  scope: rg
  name: 'talkback'
  params: {
    location: location
    tags: tags
    name: names.talkback
    serviceName: 'talkback'
    environmentId: environment.outputs.id
    identityId: identities.outputs.talkback.id
    registryServer: registry.outputs.loginServer
    exists: talkbackExists
    targetPort: 8000
    cpu: talkbackCpu
    memory: talkbackMemory
    minReplicas: talkbackMinReplicas
    maxReplicas: talkbackMaxReplicas
    appInsightsConnectionString: monitoring.outputs.connectionString
    env: concat(telemetryEnv, foundryEnv, eventHubEnv, dataEnv, [
      { name: 'AZURE_CLIENT_ID', value: identities.outputs.talkback.clientId }
      { name: 'OTEL_SERVICE_NAME', value: 'talkback' }
      { name: 'PORT', value: '8000' }
      { name: 'TALKBACK_PUBLIC_URL', value: talkbackUrl }
      { name: 'TALKBACK_CORS_ORIGINS', value: webUrl }
      { name: 'ARCHIVIST_A2A_URL', value: archivistA2aUrl }
      { name: 'LAB_A2A_URL', value: labA2aUrl }
      { name: 'ARCHIVIST_RESPONSES_URL', value: archivistResponsesUrl }
      { name: 'LAB_RESPONSES_URL', value: labResponsesUrl }
      { name: 'A2A_AGENT_CARD_PATH', value: agentCardPath }
      { name: 'A2A_VERSION', value: '1.0' }
      { name: 'A2A_TOKEN_SCOPE', value: 'https://ai.azure.com/.default' }
      { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
      { name: 'AZURE_RESOURCE_GROUP', value: rg.name }
      { name: 'GENERATOR_JOB_NAME', value: generator.outputs.name }
    ])
    // Scale on unprocessed events across the matchday partitions (KEDA azure-eventhub).
    scaleRules: [
      {
        name: 'matchday-lag'
        custom: {
          type: 'azure-eventhub'
          metadata: {
            eventHubNamespace: eventHubs.outputs.namespaceName
            eventHubName: eventHubs.outputs.hubName
            consumerGroup: eventHubs.outputs.consumerGroupName
            unprocessedEventThreshold: '200'
            activationUnprocessedEventThreshold: '1'
            storageAccountName: storage.outputs.name
            blobContainer: 'checkpoints'
            checkpointStrategy: 'blobMetadata'
          }
          identity: identities.outputs.talkback.id
        }
      }
    ]
  }
  dependsOn: [
    acrPull
  ]
}

module web 'modules/container-app.bicep' = {
  scope: rg
  name: 'web'
  params: {
    location: location
    tags: tags
    name: names.web
    serviceName: 'web'
    environmentId: environment.outputs.id
    identityId: identities.outputs.web.id
    registryServer: registry.outputs.loginServer
    exists: webExists
    targetPort: 3000
    cpu: '0.25'
    memory: '0.5Gi'
    minReplicas: webMinReplicas
    maxReplicas: 2
    env: [
      { name: 'AZURE_CLIENT_ID', value: identities.outputs.web.clientId }
      { name: 'TALKBACK_API_URL', value: talkbackUrl }
      { name: 'NEXT_PUBLIC_TALKBACK_API_URL', value: talkbackUrl }
      { name: 'PORT', value: '3000' }
      { name: 'HOSTNAME', value: '0.0.0.0' }
      { name: 'NEXT_TELEMETRY_DISABLED', value: '1' }
    ]
  }
  dependsOn: [
    acrPull
  ]
}

module mcp 'modules/container-app.bicep' = {
  scope: rg
  name: 'mcp'
  params: {
    location: location
    tags: tags
    name: names.mcp
    serviceName: 'mcp'
    environmentId: environment.outputs.id
    identityId: identities.outputs.mcp.id
    registryServer: registry.outputs.loginServer
    exists: mcpExists
    targetPort: 8000
    cpu: '0.25'
    memory: '0.5Gi'
    minReplicas: 0
    maxReplicas: 1
    appInsightsConnectionString: monitoring.outputs.connectionString
    env: concat(telemetryEnv, foundryEnv, dataEnv, [
      { name: 'AZURE_CLIENT_ID', value: identities.outputs.mcp.clientId }
      { name: 'OTEL_SERVICE_NAME', value: 'mcp' }
      { name: 'PORT', value: '8000' }
      { name: 'TALKBACK_API_URL', value: talkbackUrl }
    ])
  }
  dependsOn: [
    acrPull
  ]
}

// Plan B: the agents as internal Container Apps speaking A2A v1.0 (JSON-RPC).
// Same image as the hosted agent; TALKBACK_SERVE_MODE=a2a switches the server.
var agentAcaEnv = concat(telemetryEnv, foundryEnv, dataEnv, [
  { name: 'AZURE_CLIENT_ID', value: identities.outputs.agents.clientId }
  { name: 'TALKBACK_SERVE_MODE', value: 'a2a' }
  { name: 'PORT', value: '8088' }
])

module archivistAca 'modules/container-app.bicep' = if (agentsOnAca) {
  scope: rg
  name: 'archivist-aca'
  params: {
    location: location
    tags: tags
    name: names.archivistAca
    serviceName: 'archivist-aca'
    environmentId: environment.outputs.id
    identityId: identities.outputs.agents.id
    registryServer: registry.outputs.loginServer
    exists: archivistAcaExists
    targetPort: 8088
    external: false
    cpu: '0.5'
    memory: '1Gi'
    minReplicas: 0
    maxReplicas: 1
    appInsightsConnectionString: monitoring.outputs.connectionString
    env: concat(agentAcaEnv, [
      { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: strongModelName }
      { name: 'A2A_PUBLIC_URL', value: archivistA2aUrl }
      { name: 'OTEL_SERVICE_NAME', value: 'archivist' }
    ])
  }
  dependsOn: [
    acrPull
  ]
}

module labAca 'modules/container-app.bicep' = if (agentsOnAca) {
  scope: rg
  name: 'lab-aca'
  params: {
    location: location
    tags: tags
    name: names.labAca
    serviceName: 'lab-aca'
    environmentId: environment.outputs.id
    identityId: identities.outputs.agents.id
    registryServer: registry.outputs.loginServer
    exists: labAcaExists
    targetPort: 8088
    external: false
    cpu: '2.0'
    memory: '4Gi'
    minReplicas: 0
    maxReplicas: 1
    appInsightsConnectionString: monitoring.outputs.connectionString
    env: concat(agentAcaEnv, [
      { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: strongModelName }
      { name: 'A2A_PUBLIC_URL', value: labA2aUrl }
      { name: 'OTEL_SERVICE_NAME', value: 'lab' }
    ])
  }
  dependsOn: [
    acrPull
  ]
}

var talkbackSp = { principalId: identities.outputs.talkback.principalId, principalType: 'ServicePrincipal' }
var generatorSp = { principalId: identities.outputs.generator.principalId, principalType: 'ServicePrincipal' }
var mcpSp = { principalId: identities.outputs.mcp.principalId, principalType: 'ServicePrincipal' }
var agentsSp = { principalId: identities.outputs.agents.principalId, principalType: 'ServicePrincipal' }
var developer = empty(principalId) ? [] : [{ principalId: principalId, principalType: principalType }]

module rbac 'modules/rbac.bicep' = {
  scope: rg
  name: 'rbac'
  params: {
    foundryAccountName: foundry.outputs.accountName
    foundryProjectName: foundry.outputs.projectName
    eventHubNamespaceName: eventHubs.outputs.namespaceName
    storageAccountName: storage.outputs.name
    generatorJobName: generator.outputs.name
    foundryUsers: concat([talkbackSp, mcpSp], agentsOnAca ? [agentsSp] : [])
    contentSafetyUsers: concat([talkbackSp], developer)
    agentConsumers: assignAgentConsumerRole ? [talkbackSp, mcpSp] : []
    eventHubSenders: [generatorSp, talkbackSp]
    eventHubReceivers: [talkbackSp]
    eventHubOwners: developer
    blobContributors: concat([talkbackSp, generatorSp], developer)
    blobReaders: concat([mcpSp], agentsOnAca ? [agentsSp] : [])
    jobOperators: [talkbackSp]
  }
}

module budget 'modules/budget.bicep' = if (!empty(budgetContactEmail)) {
  scope: rg
  name: 'budget'
  params: {
    // Month in the name: re-provisioning in a later month adds a budget
    // instead of trying to move an existing budget's start date.
    name: 'budget-talkback-${budgetMonth}'
    amount: budgetAmount
    startDate: '${budgetMonth}-01'
    contactEmails: [
      budgetContactEmail
    ]
  }
}

// azd writes these into .azure/<env>/.env; azure.yaml and the apps read them.
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_ACCOUNT_ID string = foundry.outputs.accountId
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output AZURE_AI_SERVICES_ENDPOINT string = foundry.outputs.accountEndpoint
output CONTENT_SAFETY_ENDPOINT string = foundry.outputs.accountEndpoint
output FOUNDRY_MODEL_FAST string = fastModelName
output FOUNDRY_MODEL_STRONG string = strongModelName
output TALKBACK_REASONING_EFFORT_STRONG string = strongReasoningEffort

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = registry.outputs.id
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = registry.outputs.connectionName
output AZURE_CONTAINER_ENVIRONMENT_NAME string = environment.outputs.name

output EVENTHUB_FQDN string = eventHubs.outputs.fqdn
output EVENTHUB_NAME string = eventHubs.outputs.hubName
output EVENTHUB_CONSUMER_GROUP string = eventHubs.outputs.consumerGroupName
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output STORAGE_ACCOUNT_URL string = storage.outputs.blobEndpoint
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString

output TALKBACK_URL string = talkbackUrl
output WEB_URL string = webUrl
output MCP_URL string = mcp.outputs.url
output GENERATOR_JOB_NAME string = generator.outputs.name

output TALKBACK_AZURE_CLIENT_ID string = identities.outputs.talkback.clientId
output GENERATOR_AZURE_CLIENT_ID string = identities.outputs.generator.clientId
output WEB_AZURE_CLIENT_ID string = identities.outputs.web.clientId
output MCP_AZURE_CLIENT_ID string = identities.outputs.mcp.clientId
output AGENTS_AZURE_CLIENT_ID string = identities.outputs.agents.clientId

output ARCHIVIST_AGENT_NAME string = archivistAgentName
output LAB_AGENT_NAME string = labAgentName
output ARCHIVIST_A2A_URL string = archivistA2aUrl
output LAB_A2A_URL string = labA2aUrl
output ARCHIVIST_RESPONSES_URL string = archivistResponsesUrl
output LAB_RESPONSES_URL string = labResponsesUrl
output A2A_AGENT_CARD_PATH string = agentCardPath
output BUDGET_NAME string = empty(budgetContactEmail) ? 'none (set BUDGET_CONTACT_EMAIL and re-provision)' : 'budget-talkback-${budgetMonth}'
