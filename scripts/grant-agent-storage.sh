#!/usr/bin/env bash
# Give a hosted agent's own Entra identity read access to the blob storage
# (Lab snapshots). The identity only exists after `azd deploy <service>`, which
# records it as AGENT_<SERVICE>_INSTANCE_IDENTITY_PRINCIPAL_ID.
#
#   scripts/grant-agent-storage.sh [service]    (default: lab)
#
# Needs: az login with rights to create role assignments (Owner on the subscription).
set -euo pipefail

service="${1:-lab}"
key="AGENT_$(echo "$service" | tr '[:lower:]-' '[:upper:]_')_INSTANCE_IDENTITY_PRINCIPAL_ID"
principal="$(azd env get-value "$key")"
if [ -z "$principal" ]; then
  echo "$key is empty; run 'azd deploy $service' first" >&2
  exit 1
fi

scope="$(az storage account show \
  --name "$(azd env get-value STORAGE_ACCOUNT_NAME)" \
  --resource-group "$(azd env get-value AZURE_RESOURCE_GROUP)" \
  --query id -o tsv)"

# Storage Blob Data Reader
az role assignment create \
  --assignee-object-id "$principal" \
  --assignee-principal-type ServicePrincipal \
  --role 2a2b9908-6ea1-4ae2-8e65-a410df84e7d1 \
  --scope "$scope" \
  --only-show-errors > /dev/null
echo "$service ($principal): Storage Blob Data Reader on $scope"
