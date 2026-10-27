// Manually triggered Container Apps job (the matchday generator).
// Started by `az containerapp job start` or by the talkback service through ARM.

param location string
param tags object
param name string
param serviceName string
param environmentId string
param identityId string
param registryServer string
param exists bool = false

param cpu string = '0.5'
param memory string = '1Gi'

@description('Seconds before a run is killed. A compressed matchday is 9-15 minutes.')
param replicaTimeout int = 3600

param env array = []

@secure()
@description('App Insights connection string, exposed to env as secretRef appinsights-connection-string.')
param appInsightsConnectionString string = ''

var placeholderImage = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'

module current 'fetch-image.bicep' = {
  name: '${name}-current-image'
  params: {
    kind: 'job'
    name: name
    exists: exists
  }
}

var image = exists ? current.outputs.image : placeholderImage

resource job 'Microsoft.App/jobs@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': serviceName })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: replicaTimeout
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registryServer
          identity: identityId
        }
      ]
      secrets: empty(appInsightsConnectionString) ? [] : [
        {
          name: 'appinsights-connection-string'
          value: appInsightsConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'main'
          image: image
          env: env
          resources: {
            cpu: json(cpu)
            memory: memory
          }
        }
      ]
    }
  }
}

output name string = job.name
output id string = job.id
