// One Container App with a user-assigned identity, pulling from ACR with it.
// Image-based azd strategy: provision owns config, `azd deploy` swaps the image.
// On re-provision the current image is kept (exists = SERVICE_<NAME>_RESOURCE_EXISTS).

param location string
param tags object
param name string

@description('azure.yaml service name; azd finds the app by this tag.')
param serviceName string = ''

param environmentId string
param identityId string
param registryServer string
param exists bool = false

param targetPort int
param external bool = true
param minReplicas int = 0
param maxReplicas int = 1
param cpu string = '0.5'
param memory string = '1Gi'

@description('Container env entries: { name, value } or { name, secretRef }.')
param env array = []

@secure()
@description('App Insights connection string, exposed to env as secretRef appinsights-connection-string.')
param appInsightsConnectionString string = ''

param scaleRules array = []

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource existingApp 'Microsoft.App/containerApps@2025-01-01' existing = if (exists) {
  name: name
}

var image = exists ? existingApp!.properties.template.containers[0].image : placeholderImage

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: empty(serviceName) ? tags : union(tags, { 'azd-service-name': serviceName })
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
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
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
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: empty(scaleRules) ? null : scaleRules
      }
    }
  }
}

output name string = app.name
output id string = app.id
output fqdn string = app.properties.configuration.ingress.fqdn
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
