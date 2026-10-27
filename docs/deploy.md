# Deploying Talkback to Azure

One `azd up` provisions everything in `infra/` (Bicep) and ships the containers and the two Foundry hosted agents declared in `azure.yaml`.

## What gets created

One resource group, `rg-<env>`, in `swedencentral` by default:

| Resource | Name | Purpose |
|---|---|---|
| Foundry account (AIServices) + project `talkback` | `aif-<token>` | Model deployments `gpt-5.4-mini` (fast) and `gpt-6.1-sol` (strong), Global Standard; Content Safety on the same endpoint; hosted agents; tracing via the project's App Insights connection |
| Foundry hosted agents | `talkback-archivist`, `talkback-lab` | Responses protocol, with incoming A2A v1.0 and an agent card on the agent endpoint (Entra auth) |
| Container Apps environment (Consumption) | `cae-<token>` | `talkback` (API + SSE + OGraf, KEDA on Event Hubs lag), `talkback-web` (Next.js), `talkback-mcp` (MCP server), `talkback-generator` (manual job) |
| Container Registry (Basic) | `cr<token>` | Images for the apps and the hosted agents; built remotely with ACR Tasks |
| Event Hubs (Standard, 1 TU) | `evhns-<token>` | Hub `matchday`, 10 partitions (one per fixture), consumer group `talkback` |
| Storage account | `st<token>` | Blob containers `runs` (recorded broadcasts), `snapshots` (Lab), `checkpoints` (Event Hubs) |
| Cosmos DB (NoSQL, free tier) | `cosmos-<token>` | Database `talkback`: `cues`, `claims`, `verdicts`, `runs` (partition `/run_id`) and `checkpoints` (`/workflow_name`, MAF) |
| Log Analytics + Application Insights | `log-<token>`, `appi-<token>` | OpenTelemetry target for the apps; Foundry tracing |
| User-assigned identities | `id-<app>-<token>` | One per workload. No keys anywhere: storage, Event Hubs, Cosmos and Foundry have local auth turned off |
| Budget | `budget-talkback-<yyyy-MM>` | Monthly, on the resource group; alerts at 50 / 80 / 100 % actual and 100 % forecast |

Role assignments (made by the template):

| Identity | Roles |
|---|---|
| talkback | Foundry User (account), Foundry Agent Consumer (project), Event Hubs Data Sender + Receiver, Storage Blob Data Contributor, Cosmos DB Data Contributor, Container Apps Jobs Operator (generator job), AcrPull |
| generator | Event Hubs Data Sender, Storage Blob Data Contributor, Cosmos DB Data Contributor, AcrPull |
| mcp | Foundry User, Foundry Agent Consumer, Storage Blob Data Reader, Cosmos DB Data Reader, AcrPull |
| web | AcrPull |
| Foundry project identity | AcrPull (hosted-agent images), Log Analytics Data Reader (evaluations on traces) |
| you (the deploying user) | Foundry User (project), Event Hubs Data Owner, Storage Blob Data Contributor, Cosmos DB Data Contributor, so you can run the code locally against the cloud |

Each hosted agent gets its own Entra agent identity at deploy time. `azd deploy` grants it model access; anything else (for example the Lab reading `snapshots`) is `scripts/grant-agent-storage.sh lab` after the first deploy.

## Before you start

1. **A Pay-As-You-Go subscription.** Free Trial and Azure Pass subscriptions have 0 TPM for every Azure OpenAI model, so the model deployments fail. Upgrading the trial to Pay-As-You-Go in the portal keeps the remaining credit, which is used first.
2. **Owner on the subscription.** The template creates role assignments.
3. **Model quota in the region.** New subscriptions start in a quota tier. Check it:

   ```bash
   az rest --method get \
     --url "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/providers/Microsoft.CognitiveServices/quotaTiers?api-version=2025-10-01-preview"
   az cognitiveservices usage list --location swedencentral -o table | grep -i -E "gpt-5.4-mini|gpt-6.1-sol"
   ```

   Tier 1 gives Global Standard 1M TPM for `gpt-5.4-mini` and 250K TPM for `gpt-6.1-sol`; the template asks for 50K each. The free tier (tier 0) only covers `gpt-4.1-mini`, `gpt-5-mini` and `o4-mini`. If that is what you have, switch the models before provisioning:

   ```bash
   azd env set FAST_MODEL_NAME gpt-5-mini
   azd env set FAST_MODEL_VERSION 2025-08-07
   azd env set STRONG_MODEL_NAME o4-mini
   azd env set STRONG_MODEL_VERSION 2025-04-16
   ```

   Other strong options with Global Standard in Sweden Central: `gpt-6-sol` (`2026-09-22`), `gpt-5.6-sol` (`2026-07-09`), `gpt-5.4` (`2026-03-05`).
4. **Tools.** Azure CLI 2.80+, Azure Developer CLI 1.37+, and the Foundry extensions:

   ```bash
   azd ext install microsoft.foundry      # installs azure.ai.agents, azure.ai.projects, ...
   azd ext list --installed               # azure.ai.agents must be 1.0.0-beta.22 or later
   ```

   Docker is optional. Images build in ACR (`remoteBuild: true`); azd falls back to local Docker only if the subscription can't run ACR Tasks.

## Deploy

From the repository root:

```bash
az login
azd auth login                          # same account and tenant as az
az account set --subscription <subscription-id>

azd env new talkback --location swedencentral --subscription <subscription-id>
azd env set BUDGET_CONTACT_EMAIL <you@example.com>
# optional: azd env set BUDGET_AMOUNT 60

azd up
```

`azd up` runs `azd provision` (about 10-15 minutes, mostly the Foundry account, Cosmos DB and the Container Apps environment) and then `azd deploy` for every service.

While parts of the code are still landing, provision once and deploy service by service:

```bash
azd provision
azd deploy archivist
azd deploy lab
azd deploy talkback     # needs talkback.service.app
azd deploy generator    # needs talkback.service.generator
azd deploy mcp          # needs talkback.mcp.server
azd deploy web          # needs web/ with output: "standalone"
```

A service whose module doesn't exist yet still deploys, then crash-loops; `web` fails to build without `web/`. Re-running `azd provision` later keeps the deployed images.

## Check it

```bash
azd env get-values                      # every endpoint and name the apps use
azd ai agent doctor                     # local + remote checks for the hosted agents
azd ai agent show archivist
azd ai agent endpoint show archivist    # protocols should list responses and a2a, plus the card
scripts/a2a.sh card                     # v1.0 agent cards, with your Entra token
scripts/a2a.sh ping                     # one A2A v1.0 SendMessage per agent
azd ai agent invoke archivist "Moment: goal at 61'. Story board: (empty)"
```

If `endpoint show` doesn't list `a2a`, apply the endpoint and card from `azure.yaml` without a new version:

```bash
azd ai agent endpoint update archivist
azd ai agent endpoint update lab
```

Start a live matchday (the API can do the same through ARM with its identity):

```bash
az containerapp job start --name talkback-generator --resource-group "$(azd env get-value AZURE_RESOURCE_GROUP)"
```

Logs: `azd ai agent monitor archivist --tail 100`, `az containerapp logs show -n talkback -g <rg> --follow`, and Application Insights (Transaction search) for traces. Foundry shows the hosted agents' traces under the project.

## What the apps receive

Every container gets `AZURE_CLIENT_ID` for its own identity, so `DefaultAzureCredential()` picks the managed identity. The talkback service also gets:

| Variable | Value |
|---|---|
| `TALKBACK_LLM` | `foundry` |
| `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_FAST`, `FOUNDRY_MODEL_STRONG` | project endpoint and the two deployment names |
| `CONTENT_SAFETY_ENDPOINT` | the Foundry account endpoint (`https://aif-<token>.cognitiveservices.azure.com/`) |
| `EVENTHUB_FQDN`, `EVENTHUB_NAME`, `EVENTHUB_CONSUMER_GROUP` | `evhns-<token>.servicebus.windows.net`, `matchday`, `talkback` |
| `STORAGE_ACCOUNT_URL`, `STORAGE_CONTAINER_RUNS` / `_SNAPSHOTS` / `_CHECKPOINTS` | blob endpoint and container names |
| `COSMOS_ENDPOINT`, `COSMOS_DATABASE` | plus `AZURE_COSMOS_ENDPOINT`, `AZURE_COSMOS_DATABASE_NAME`, `AZURE_COSMOS_CONTAINER_NAME=checkpoints` for MAF's `CosmosCheckpointStorage` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING`, `OTEL_SERVICE_NAME` | telemetry (the connection string is a Container Apps secret) |
| `ARCHIVIST_A2A_URL`, `LAB_A2A_URL`, `A2A_AGENT_CARD_PATH`, `A2A_VERSION`, `A2A_TOKEN_SCOPE` | A2A base URLs, `agentCard/v1.0`, `1.0`, `https://ai.azure.com/.default` |
| `TALKBACK_PUBLIC_URL`, `TALKBACK_CORS_ORIGINS` | the API's own URL and the web origin |
| `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `GENERATOR_JOB_NAME` | to start the generator job |

Notes for the service code:

- **Event Hubs checkpoints** go to the `checkpoints` blob container through `azure-eventhub-checkpointstoreblob-aio` (blob-metadata checkpoints). The KEDA rule reads the same blobs to compute lag.
- **Cosmos documents** carry `run_id` (the partition key) in `cues`, `claims`, `verdicts` and `runs`. Containers exist already; data-plane RBAC can't create them.
- **Hosted-agent sessions.** A Responses or A2A call without a session lands in a new sandbox. Reuse one conversation (or `agent_session_id`) per match and agent. The agents' idle timeout is 120 s, so a stray sandbox costs about two minutes of compute.
- **SSE.** Container Apps ingress has a 240 s request timeout. Send a heartbeat comment every 15-30 s and support reconnects with `Last-Event-ID` (browsers' `EventSource` reconnects on its own), so a 9-15 minute matchday stream survives either way.
- **Replicas.** `talkback` runs one replica (`TALKBACK_MAX_REPLICAS=1`) until matchday state is shared across replicas; raise it to 10 to let KEDA scale with the partitions.

## Plan B: agents as Container Apps

If hosted agents can't be deployed, run the same agent images as internal Container Apps that serve A2A v1.0 (JSON-RPC, card at `/.well-known/agent-card.json`):

1. `azd env set AGENTS_ON_ACA true`
2. In `azure.yaml`, replace the `archivist` and `lab` services with:

   ```yaml
     archivist-aca:
       host: containerapp
       language: docker
       project: agents/archivist
       docker:
         path: Dockerfile
         context: ../..
         remoteBuild: true
     lab-aca:
       host: containerapp
       language: docker
       project: agents/lab
       docker:
         path: Dockerfile
         context: ../..
         remoteBuild: true
   ```

3. `azd provision && azd deploy archivist-aca && azd deploy lab-aca`

`ARCHIVIST_A2A_URL` and `LAB_A2A_URL` then point at `https://archivist.internal.<env-domain>` and `https://lab.internal.<env-domain>`, and `A2A_AGENT_CARD_PATH` becomes `.well-known/agent-card.json`. The apps are reachable only inside the Container Apps environment.

## Settings

Set with `azd env set NAME value`, then `azd provision`.

| Variable | Default | Meaning |
|---|---|---|
| `AZURE_LOCATION` | `swedencentral` | Region for everything |
| `FAST_MODEL_NAME` / `_VERSION` / `_CAPACITY` | `gpt-5.4-mini` / `2026-03-17` / `50` | Fast tier (capacity in thousands of TPM) |
| `STRONG_MODEL_NAME` / `_VERSION` / `_CAPACITY` | `gpt-6.1-sol` / `2026-09-29` / `50` | Strong tier |
| `BUDGET_CONTACT_EMAIL` | (empty) | Required for the budget; empty skips it (`BUDGET_NAME` output says so) |
| `BUDGET_AMOUNT` | `60` | Monthly budget, in the billing currency |
| `TALKBACK_MIN_REPLICAS` / `TALKBACK_MAX_REPLICAS` | `1` / `1` | API replicas |
| `WEB_MIN_REPLICAS` | `1` | `0` saves money but adds a cold start to the landing page |
| `COSMOS_FREE_TIER` | `true` | `false` (serverless) if the subscription already has a free-tier account |
| `EVENTHUB_SKU` | `Standard` | `Basic` is cheaper but has no custom consumer group (uses `$Default`) |
| `LOG_DAILY_CAP_GB` | `0.5` | Log Analytics daily cap |
| `AGENTS_ON_ACA` | `false` | Plan B |
| `ASSIGN_AGENT_CONSUMER_ROLE` | `true` | `false` if the tenant doesn't have the Foundry Agent Consumer role yet (Foundry User still covers agent endpoints) |

Region notes: Sweden Central has both models in Global Standard, hosted agents, Container Apps, Event Hubs and Cosmos DB. Poland Central, France Central and Germany West Central also list both models in Global Standard; check hosted-agent availability before switching. Global Standard can process prompts in any Azure region; the data here is synthetic.

## Cost until Nov 10

Retail prices for Sweden Central (USD, Azure retail prices API, Oct 2026), for the 15 days from Oct 27 to Nov 10:

| Item | Rate | Assumption | Estimate |
|---|---|---|---|
| Event Hubs Standard, 1 TU | $0.03 per TU-hour | always on | $10.80 |
| Container Registry Basic | $0.167 per day | builds within the free task minutes | $2.50 |
| Container Apps: `talkback` 1 vCPU / 2 GiB, min 1 | vCPU $0.000024/s active, $0.000003/s idle; memory $0.000003 per GiB-s | about 4 h/day active | $16 |
| Container Apps: `talkback-web` 0.25 vCPU / 0.5 GiB, min 1 | same | mostly idle | $3 |
| Container Apps: `talkback-mcp`, generator job | scale to zero | about 40 matchday runs | $1 |
| Container Apps monthly free grant | 180,000 vCPU-s + 360,000 GiB-s per month, Oct and Nov | | -$5 to -$8 |
| Cosmos DB free tier | 1000 RU/s + 25 GB free | | $0 |
| Storage (LRS, hot) | | a few GB of runs and snapshots | < $0.50 |
| Log Analytics / App Insights | first 5 GB per month free, then $2.99/GB | capped at 0.5 GB/day | $0-2 |
| Foundry hosted agents | $0.109 per vCPU-hour + $0.013 per GiB-hour while a session runs | Archivist 0.5 vCPU / 1 GiB = $0.068/h; Lab 2 vCPU / 4 GiB = $0.27/h; 120 s idle timeout | $2-8 |
| **Infrastructure subtotal** | | | **about $30-35** |
| Model tokens | `gpt-5.4-mini` $0.75 in / $4.50 out per 1M; `gpt-6.1-sol` $2 in / $10 out per 1M (short context); cached input $0.075 / $0.10 | | per matchday, below |

Tokens per matchday, as an example: 1,000 fast calls at 2K in / 250 out is about $2.60; 300 strong calls at 3K in / 300 out is about $2.70. That is roughly $5 per matchday, so a $60 budget leaves room for four or five full matchdays after the infrastructure. Stable system prompts get the cached-input price. The live cost per matchday comes from token usage and is shown on the proof page.

To spend less without tearing down: `azd env set WEB_MIN_REPLICAS 0` and `TALKBACK_MIN_REPLICAS 0`, then `azd provision` (first visitor waits for a cold start).

## Tear down

```bash
azd down --purge --force
```

This deletes the resource group (apps, hosted agents, data, budget). `--purge` also removes the soft-deleted Foundry account, which otherwise keeps its name and quota reserved for 48 hours. Recorded runs in blob storage go with it; copy `runs` out first if you need them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `InsufficientQuota` / `DeploymentModelNotSupported` on a model deployment | Check the quota tier and usage (above); lower `*_MODEL_CAPACITY` or switch models |
| `Free tier ... already applied` on Cosmos DB | `azd env set COSMOS_FREE_TIER false` |
| `RoleDefinitionDoesNotExist` for `eed3b665-...` | `azd env set ASSIGN_AGENT_CONSUMER_ROLE false` |
| `TasksOperationsNotAllowed` during deploy | azd builds locally instead; start Docker and rerun `azd deploy` |
| Hosted agent version `failed` with `image_pull_failed` | The project identity needs AcrPull on the registry (the template grants it); check `az acr config authentication-as-arm show -r <registry>` is enabled |
| Hosted agent starts but answers with errors about `talkback.hosted` | The image serves a fallback agent until `talkback.hosted.<name>.build_agent()` exists; see `agents/common/hosting.py` |
| KEDA scale rule errors | `az containerapp logs show -n talkback -g <rg> --type system` |
| `azd provision` resets an app's image | It shouldn't: `SERVICE_<NAME>_RESOURCE_EXISTS` keeps the deployed image. Run `azd deploy <service>` once if a service was never deployed |
