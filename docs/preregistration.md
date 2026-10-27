# Evaluation pre-registration

Committed before any evaluation run of record. The answer keys below were sealed when the matchdays were
generated; their SHA-256 is recomputed by `talkback eval` and must match.

## Matchdays

Generate any of them with `uv run talkback matchday --seed <seed> --out runs/md-<seed>` (deterministic).

| Seed | Key SHA-256 | Must-surface storylines |
|---|---|---|
| 2026 | `768c07185cbe1455d16eb508a95261174e266c04ad3f3ab8d12933f22083c37a` | 11 |
| 2027 | `aaf8ca691d11d495476c31c479116b536c234ecf6d4576c9eb9ccd80ad325117` | 10 |
| 2028 | `97369af9f813c6f5be5bb12000304b5cd5352fb0760fe2f795dbe2af2a54569c` | 11 |
| 2029 | `de6a811161f9756ee6a8304f5e524aa9e34500dce0646b25d86040e824451809` | 8 |
| 2030 | `d0ba8defaee8e77ac45f39bc8782b288760c5d9318103ed42eb69f305e703246` | 8 |

48 must-surface storylines in total. A storyline is *must* when the key says so after play: pre-match
stories always; a milestone, a former-club goal or a scoring-race goal only if it happened; an unbeaten run
or a clean-sheet record at full time.

## Systems

1. **Talkback** — the full gallery; only lines that reached air in a territory count.
2. **Talkback without Clearance** — the same run, counting every drafted line (first drafts before any
   revision, including refused ones) as if it had aired everywhere in English. This is the negative control:
   it shows what the gate removes.
3. **Single model** — one model call per match per 15-minute segment and one at full time, given the same
   season data sheet for both line-ups, the same events (summarised) and the same model as Talkback's
   writer. Its lines count as aired in every territory.

All three use the same Foundry deployments.

## Metrics (identical code for every system: `src/talkback/eval`)

* **Story Recall** — must-surface storylines that reached air in time: a live line naming one of the
  story's subjects with language of that kind of story (see `eval/detect.py`), inside the story's window
  (pre-match stories: first 20 minutes; event stories: 5 minutes after the event), or in the recap for
  full-time stories. Reported with the number surfaced late and missed.
* **Unverifiable numbers** — numbers in aired English lines that match no value the gallery could have cited
  at that time (any Fact of that match, season data, minutes and counts).
* **Over-claims in thin windows** — aired lines in the first 8 minutes whose wording reaches strength level 2
  or more.
* **Spoilers in the delayed territory** — lines aired to MENA naming a club from another match within two
  minutes after that match scored.
* **Trivia intrusion** — lines featuring one of the planted trivial facts.
* **Latency** — the moment's match time to the line's air time, at 1x (pipeline wall time).

Air time for Talkback lines is the moment's match time plus the measured pipeline latency, so a run played
out faster than real time is scored as if it had aired live.

## What would count against us

We will publish the numbers whichever way they fall, including any metric where the single model is level
with or better than Talkback.
