// Event Hubs: one hub for the whole matchday, one partition per fixture.

param location string
param tags object
param namespaceName string
param hubName string = 'matchday'
param partitionCount int = 10
param consumerGroupName string = 'talkback'

@allowed(['Basic', 'Standard'])
param sku string = 'Standard'
param capacity int = 1

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: sku
    tier: sku
    capacity: capacity
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    isAutoInflateEnabled: false
    zoneRedundant: false
  }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: namespace
  name: hubName
  properties: {
    partitionCount: partitionCount
    messageRetentionInDays: 1
  }
}

// Basic tier only has $Default.
resource consumerGroup 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = if (sku != 'Basic') {
  parent: hub
  name: consumerGroupName
}

output namespaceName string = namespace.name
output namespaceId string = namespace.id
output fqdn string = '${namespace.name}.servicebus.windows.net'
output hubName string = hub.name
output consumerGroupName string = sku == 'Basic' ? '$Default' : consumerGroupName
