// The image a container app or job runs now, so re-provisioning keeps the deployed image. A separate
// deployment: reading the resource in the template that also declares it is a circular dependency.
@allowed(['app', 'job'])
param kind string
param name string
param exists bool

resource existingApp 'Microsoft.App/containerApps@2025-01-01' existing = if (exists && kind == 'app') {
  name: name
}

resource existingJob 'Microsoft.App/jobs@2025-01-01' existing = if (exists && kind == 'job') {
  name: name
}

output image string = !exists ? '' : kind == 'app'
  ? existingApp!.properties.template.containers[0].image
  : existingJob!.properties.template.containers[0].image
