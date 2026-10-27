# Proof

What we measured, how, and where to check it. Every claim and its evidence type is listed in
[CLAIMS.md](CLAIMS.md); what is real and what is simulated is in [MOCKS.md](MOCKS.md).

## 1. The evaluation of record

Pre-registered in [preregistration.md](preregistration.md): the systems, the metrics and, for every matchday, the
SHA-256 of its sealed answer key, published before the matchday was played. The record is five held-out matchdays
(seeds 2031–2035) played by a build fixed before they were generated; the five development matchdays (2026–2030)
are the ones the gallery was tuned on. `talkback eval` refuses to score a run whose key does not match its sealed
hash.

<!-- EVAL-RESULTS -->
### Evaluation of record (held-out seeds 2031–2035)

5 matchdays, 10 matches each; sealed keys `da564bdbeba1…`, `28c3880591d6…`, `63511255a261…`, `8dbab58f1429…`, `b504403f30a7…`

| | Talkback | Single model | Clearance off |
|---|---|---|---|
| Story Recall (must-surface storylines on air in time) | **69%** (33/48) | **25%** (12/48) | **92%** (44/48) |
| …surfaced late / missed | 1 / 14 | 8 / 28 | 1 / 3 |
| Unverifiable numbers on air | 1.5% (15/997) | 0.1% (2/1916) | 2.6% (60/2315) |
| Over-claims in the first 8 minutes | 0 | 0 | 9 |
| Spoilers inside MENA's two-minute delay | 6 | 76 | 54 |
| Trivia that reached air | 1 | 0 | 1 |
| Lines on air (English) | 1070 | 1186 | 2006 |
<!-- EVAL-RESULTS -->

### Development set (seeds 2026–2030)

The gallery was tuned while these matchdays were scored (see the amendments in the pre-registration), so they show the direction, not the record.

5 matchdays, 10 matches each; sealed keys `768c07185cbe…`, `aaf8ca691d11…`, `97369af9f813…`, `de6a811161f9…`, `d0ba8defaee8…`

| | Talkback | Single model | Clearance off |
|---|---|---|---|
| Story Recall (must-surface storylines on air in time) | **48%** (23/48) | **25%** (12/48) | **81%** (39/48) |
| …surfaced late / missed | 1 / 24 | 11 / 25 | 2 / 7 |
| Unverifiable numbers on air | 1.1% (6/547) | 0.0% (0/1949) | 7.7% (151/1953) |
| Over-claims in the first 8 minutes | 0 | 0 | 9 |
| Spoilers inside MENA's two-minute delay | 0 | 47 | 50 |
| Trivia that reached air | 3 | 2 | 9 |
| Lines on air (English) | 593 | 1168 | 1680 |

**How it ran.** Every system used the same Microsoft Foundry deployments: `gpt-5-mini` (2025-08-07, reasoning effort
low) for the Archivist, the Lab and the full-time Recap; `gpt-4.1-mini` (2025-04-14) for the Spotter, the Writer,
the territory desks and the single-model baseline. Azure AI Content Safety checked every Talkback line. The gallery
played each matchday at 6x; a line's age and latency are measured in wall time from the moment it was spotted, so
waiting in the queue and for the producer counts as it would at 1x. For the evaluation the Archivist and the Lab ran
in the gallery's process on the same models; the deployed gallery calls them as Foundry hosted agents.

Reproduce:

```bash
uv run talkback eval-all --seeds 2031 2032 2033 2034 2035 --speed 6 --web web/public/eval/summary.json
```

## 2. The simulator is a credible world

500 simulated matches between the fictional clubs land inside public per-match ranges on all ten statistics
(goals, shots, shots-on-target share, passes, completion, PPDA, fouls, corners, cards, distance). Full table and
method: [calibration.md](calibration.md). Reproduce: `uv run python -m talkback.sim.calibrate --n 500`.

## 3. The rules are code, and the code is tested

`uv run pytest -q -m "slow or not slow"` runs the full suite (373+ tests). The ones behind each claim are named in
[CLAIMS.md](CLAIMS.md): number recompute and attribution, strength against evidence, causal words against a Lab
interval, staleness at air time, territory packs and the MENA embargo, producer holds, fail-closed paths, the
sealed Lab answer, the eval's scoring.

## 4. It runs on Azure

| | Where |
|---|---|
| Web console | <https://talkback-web.whitegrass-fc8cab89.swedencentral.azurecontainerapps.io> |
| Gallery service and OGraf Server API | <https://talkback.whitegrass-fc8cab89.swedencentral.azurecontainerapps.io/api/health>, `/ograf/v1` |
| MCP server | <https://talkback-mcp.whitegrass-fc8cab89.swedencentral.azurecontainerapps.io> |
| Foundry hosted agents | `talkback-archivist`, `talkback-lab` in the Foundry project `talkback` (Sweden Central) |
| Feed, ledger, runs | Azure Event Hubs (one partition per match), Azure Cosmos DB, Azure Blob Storage |

Everything is provisioned from `infra/` with `azd provision`; [deploy.md](deploy.md) has the steps, the roles each
identity gets and what it costs.
