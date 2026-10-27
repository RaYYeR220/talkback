#!/usr/bin/env bash
# Prove incoming A2A v1.0 on the Foundry hosted agents.
#
#   scripts/a2a.sh card [agent...]           fetch the v1.0 agent card
#   scripts/a2a.sh ping [agent...] [-- text]  send one A2A v1.0 SendMessage (JSON-RPC)
#
# Agents default to ARCHIVIST_AGENT_NAME and LAB_AGENT_NAME from the azd env.
# If the card is missing after `azd deploy`, run `azd ai agent endpoint update <service>`.
# Needs: az login (same account as azd) with Foundry User or Foundry Agent Consumer.
set -euo pipefail

cmd="${1:-card}"
shift || true
agents=()
text="Say in one line what you can do."
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--" ]; then shift; text="$*"; break; fi
  agents+=("$1"); shift
done
if [ "${#agents[@]}" -eq 0 ]; then
  agents=("$(azd env get-value ARCHIVIST_AGENT_NAME)" "$(azd env get-value LAB_AGENT_NAME)")
fi

endpoint="$(azd env get-value FOUNDRY_PROJECT_ENDPOINT)"
endpoint="${endpoint%/}"
token="$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)"

for agent in "${agents[@]}"; do
  base="$endpoint/agents/$agent/endpoint/protocols/a2a"
  case "$cmd" in
    card)
      echo "== $agent: $base/agentCard/v1.0"
      curl -fsS "$base/agentCard/v1.0" -H "Authorization: Bearer $token"
      echo
      ;;
    ping)
      echo "== $agent: SendMessage (A2A-Version 1.0)"
      body=$(printf '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"ping-%s","role":"ROLE_USER","parts":[{"text":"%s"}]}}}' "$(date +%s)" "$text")
      curl -fsS -X POST "$base" \
        -H "Authorization: Bearer $token" -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
        -d "$body"
      echo
      ;;
    *)
      echo "usage: $0 card|ping [agent...] [-- text]" >&2
      exit 2
      ;;
  esac
done
