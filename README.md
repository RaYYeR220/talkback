# Talkback

**The stat was right. The story was missing.**

Talkback is an AI editorial gallery for a whole football matchday. Ten matches kick off at once. A crew of
specialised agents finds the stories a busy matchday buries, proves every line it wants to say, clears each
line separately for every territory it will air in, and cues approved lines to the presenter and onto
broadcast graphics.

> Live gallery · Demo video · [Review in five minutes](docs/JUDGES.md) · [Proof](docs/PROOF.md) · [What we claim](docs/CLAIMS.md)

---

## Why

Sports AI products already check their numbers. That is not where they fail on air.

* **They miss the story.** An automated recap can get every score right and still leave out the farewell
  match, the hundredth goal or the debut a club's fans tuned in for. Precision checks cannot see an omission.
* **They say it too strongly.** "Dominant" after four minutes and two shots is not a wrong number. It is a
  claim the evidence does not support.
* **They say it everywhere the same way.** A broadcaster serves many markets. A line that is fine in the UK
  can be a gambling reference in Spain, a spoiler in a territory that airs two minutes late, or unsuitable for
  a children's feed.

Talkback is built around these three failures. It measures **Story Recall** (did the stories that had to reach
air reach air), it enforces **wording that matches the evidence**, and it **clears every line per territory**
before it is cued.

## What happens to one moment

```
goal at 56′ in Calder Vale v Ashcombe Rovers
  Spotter      ranks it among the moments of the last 5 seconds on ten pitches
  Archivist ┐  finds the storyline: the scorer was on 99 career goals          (A2A, Foundry hosted agent)
  Lab       ┘  replays the moment 160 times without the shot → effect on threat (A2A, Foundry hosted agent)
  Writer       drafts analyst, casual and presenter lines; every number cites a fact, every story a storyline
  Clearance    recomputes numbers and attribution, checks wording strength and causal words,
               then five territory desks localise and apply their packs in parallel
  Producer     approves anything sensitive (injuries, discipline, refereeing); silence means it does not air
  Graphics Op  books OGraf graphics per territory output, timed against each territory's broadcast delay
  Prompter     puts the 14-word presenter line in the talkback ear
  Recap        at full time, the match story under the same rules
```

## The agents

| Agent | Kind | Job |
|---|---|---|
| **Feed** | code | Consumes the matchday feed (Event Hubs, one partition per match) and keeps match state |
| **Stats Desk** | code | Every metric as a *Fact*: value, window, sample size and the event ids it came from (xG, xT, pass difficulty, PPDA, field tilt, momentum, win probability, distance, top speed, pitch control) |
| **Spotter** | rules + model | Deterministic triggers propose moments; a fast model ranks them |
| **Archivist** | model + tools | Finds season storylines in the raw data (careers, previous clubs, table, streaks, records) and decides which a moment makes due |
| **Lab** | model + simulator | Earns causal words: picks a counterfactual, the simulator replays it with paired random numbers, a claim is supported only if the 95% interval excludes zero |
| **Director** | code + model | Allocates the world feed's attention across ten matches; keeps the live table with title, top-four and relegation chances, and attributes every swing to the match that caused it |
| **Writer** | model | Drafts lines per audience with structured claims; gets one revision with Clearance's reasons |
| **Clearance** | code + model desks | The gate. Universal checks, then per-territory desks (localise, re-check, apply the pack). Fails closed |
| **Graphics Op** | code | OGraf v1 graphics driven through the OGraf Server API, per territory output |
| **Prompter** | code | Presenter cue strip (IFB), timed to the delay budget |
| **Recap** | model | Full-time recap under the same evidence rules |
| **Producer** | human | Approves or rejects holds in the console; unanswered holds expire as not aired |

**Why not one agent:** ten live streams, a story board that persists across the matchday, a simulator loop,
per-territory clearance and a gate that must not be the author of what it checks. The evaluation runs the
same models as a single agent on the same data, so the difference is measured, not asserted.

## Architecture

```mermaid
flowchart LR
  G[Generator<br/>Container Apps job] -- events + tracking<br/>10 partitions --> EH[(Event Hubs)]
  G -- run, snapshots --> B[(Blob storage)]
  EH --> T
  subgraph T[talkback service · Container Apps]
    direction TB
    F[Feed + Stats Desk] --> S[Spotter] --> W{{Agent Framework workflow<br/>per moment}}
    W --> C[Clearance + territory desks]
    C --> P[Producer HITL]
    D[Director + live table]
  end
  W <-. A2A v1.0 .-> A[Archivist<br/>Foundry hosted agent]
  W <-. A2A v1.0 .-> L[Lab<br/>Foundry hosted agent]
  A & L --> B
  W --> M[Foundry models]
  C --> CS[Content Safety]
  T --> O[OGraf Server API] --> R[renderer outputs<br/>world · uk · es · mena · kids · br · presenter]
  T --> CO[(Cosmos DB<br/>claim ledger)]
  T --> AI[App Insights / Foundry tracing]
  T --> X[MCP server]
  T --> UI[Web console]
```

Solid arrows are wired and exercised in the tests. The Archivist and Lab calls are dotted because they run
over the network: when an A2A call fails the workflow runs the same agent in process and marks the moment
*degraded*.

## The synthetic world

No real data, clubs or players are used anywhere.

* **A fictional league** of 20 clubs with playing styles, 25-man squads and career histories, backfilled for
  eleven matchdays.
* **A 10 Hz agent-based match engine** (`src/talkback/sim`). Players move to formation targets under
  acceleration and speed limits, the ball carrier scores pass, carry, shot and cross options, and duels, set
  pieces, cards, substitutions and game-state tactics run on the same clock. Every match is reproducible from
  (fixture, seed) and can be snapshotted and restored, which is what the Lab replays.
* **Calibrated against public league averages** over 500 matches: goals, shots, shots on target, passes,
  completion, PPDA, fouls, corners, cards and distance are all inside their target ranges. See
  [docs/calibration.md](docs/calibration.md).
* **Planted storylines with a sealed key.** Each matchday plants milestones, farewells, debuts, reunions,
  races, records and relegation stakes into the data. Which of them *must* reach air is decided after play and
  sealed with a SHA-256 before any evaluation runs. The gallery never sees the key; it has to find the
  stories in the data.

## Clearance

Every rule is code, and every failure is a refusal.

1. **Numbers and attribution.** Every number in the text must be a claim citing a Fact, Experiment or
   Storyline with that value — and the claim's subject must be the subject of the Fact. A right number on the
   wrong player is refused.
2. **Strength.** A lexicon maps words to levels. "Edging" needs a little evidence, "dominant" needs a large
   sample, a long window and a real edge over the opponent.
3. **Causal words** ("because", "cost them") need a Lab experiment whose interval excludes zero.
4. **Staleness.** A line is re-checked against the match state when it would air; a goal in between kills it.
5. **Content Safety** on every outgoing line.
6. **Territory packs** (`src/talkback/clearance/packs`): UK, Spain, Brazil, MENA (Arabic, two-minute
   delay, results embargo) and a kids feed. Each desk localises the line and the gate re-checks the localised
   text before the pack applies. The packs are illustrative editorial templates, not legal advice.

## Microsoft platform

| | Used for |
|---|---|
| **Microsoft Agent Framework 1.23** | The per-moment workflow (fan-out, fan-in, request/response pauses for the producer), agents, tools, middleware, A2A client and server |
| **Microsoft Foundry** | Models for every agent, hosted agents for the Archivist and the Lab (A2A v1.0 endpoints, Entra agent identities), tracing |
| **Azure Container Apps** | The talkback service, MCP server and web console; the generator as a job |
| **Azure Event Hubs** | The live matchday feed, one partition per match |
| **Azure Cosmos DB** | The claim ledger: every line with its claims, evidence and verdicts |
| **Azure Blob Storage** | Runs and engine snapshots shared with the hosted agents |
| **Azure AI Content Safety** | Every outgoing line |
| **Application Insights** | OpenTelemetry from the service and the agents |
| **azd + Bicep** | One-command provisioning (`infra/`, `azure.yaml`) |

## Integrate

* **MCP** — `python -m talkback.mcp.server`: read-only tools over the live gallery (matches, aired lines,
  refused lines with reasons, story boards, the live table, and `explain_line` for the evidence behind any
  line). Works from GitHub Copilot agent mode or any MCP client.
* **OGraf** — `/ograf/v1` is an EBU OGraf v1 Server API; `/ograf/renderer/?renderer=uk` is a renderer page
  usable as an HTML source in a vision mixer. The graphics packages in `ograf/graphics` run on any OGraf
  renderer. Reading the API and the renderer pages is public; calls that change graphics need
  `Authorization: Bearer $TALKBACK_OGRAF_TOKEN` (unset, the service makes a token per process for its own
  Graphics Op).
* **A2A** — the Archivist and the Lab publish agent cards and answer A2A v1.0 JSON-RPC.
* **Schemas** — `docs/schemas` has the JSON Schema of every shared object (Event, Fact, Storyline, Claim,
  Cue, verdicts). Territory packs are plain YAML.

## Run it

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest -q                                   # unit and integration tests
uv run talkback matchday --seed 2026 --out runs/md-2026
uv run uvicorn talkback.service.app:app --port 8000
```

The service replays the recorded run in `runs/md-2026/broadcast-replay.jsonl` until a live matchday is
started from the console. A live run needs a model provider:

| Variable | Meaning |
|---|---|
| `TALKBACK_LLM` | `foundry` (default in Azure) |
| `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_FAST`, `FOUNDRY_MODEL_STRONG` | Foundry project and deployments |
| `CONTENT_SAFETY_ENDPOINT` | Content Safety (without it, local runs need `TALKBACK_ENV=dev`) |
| `ARCHIVIST_A2A_URL`, `LAB_A2A_URL` | Hosted agents over A2A (in-process when unset) |
| `EVENTHUB_FQDN`, `STORAGE_ACCOUNT_URL`, `COSMOS_ENDPOINT`, `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure services |

Deploy to Azure: see [docs/deploy.md](docs/deploy.md).

## Honest limits

* The match engine is calibrated to aggregate levels, not fitted to real matches; it is a credible world to
  test editorial behaviour in, not a forecasting model.
* Spelled-out numbers ("nine shots") are not extracted by the number check. Strength words outside the
  lexicon are not caught.
* Territory packs are templates, not legal advice.
* Auto-eventing from video, Microsoft Fabric and Teams publishing are not part of this build.

## License

MIT
