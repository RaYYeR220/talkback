# Review Talkback in five minutes

No login, keys or install needed for steps 1–4.

1. **Open the gallery** — the console replays the latest recorded matchday (marked REPLAY) until someone
   starts a live one. Watch the ten-match wall, the Director's "now showing … because …", and the program
   monitor with the territory switcher (World, UK, ES, MENA, KIDS, BR).
2. **Open the clearance matrix** and click a red cell: every refused line shows the rule that refused it
   (a number with no source, the right number on the wrong player, "dominant" on four minutes of evidence,
   a gambling word in Spain, another match's score inside MENA's two-minute delay, an injury on the kids feed).
3. **Click any aired line** to open its ledger: the claims, the facts and event ids they cite, and the Lab
   experiment behind any causal word (as played vs counterfactual, with the 95% interval).
4. **Open the story board** of a match: the storylines the Archivist found in the season data and which of
   them reached air. The Story Recall meter is the headline number in [PROOF.md](PROOF.md).
5. **Start a live matchday** with *Go live* (one at a time, capped per day). Holds appear in the producer
   queue; approve or reject them, or let them expire, which means they do not air.

## What to check in the code

| Claim | Where |
|---|---|
| The per-moment Agent Framework workflow (fan-out, fan-in, producer pause and resume) | `src/talkback/gallery/workflow.py` |
| Clearance rules and territory packs | `src/talkback/clearance/` |
| Counterfactual rollouts with paired random numbers | `src/talkback/sim/rollout.py`, `src/talkback/gallery/agents/lab.py` |
| Hosted agents and A2A v1.0 | `agents/`, `src/talkback/hosted/`, `src/talkback/gallery/remote.py` |
| OGraf Server API and graphics | `src/talkback/ograf/`, `ograf/graphics/` |
| Sealed answer key and evaluation | `src/talkback/world/key.py`, `src/talkback/eval/`, [preregistration.md](preregistration.md) |
| Infrastructure | `infra/`, `azure.yaml`, [deploy.md](deploy.md) |

Every claim and its evidence: [CLAIMS.md](CLAIMS.md). What is real and what is simulated: [MOCKS.md](MOCKS.md).
