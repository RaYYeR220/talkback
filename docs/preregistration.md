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

## Amendments (before any run of record)

2026-10-27, after a review of the scoring code and before any evaluation run of record. The text above and the
sealed key hashes are unchanged.

* **Story Recall** — a system that aired nothing on a matchday is scored there as missing every must-surface
  storyline, and totals sum over every matchday; before, such a matchday dropped out of that system's recall.
* **Spoilers in the delayed territory** — a line aired to MENA is checked in its English source as well as in the
  aired text, for every system; Talkback's MENA lines are in Arabic, so a check on club names in Latin script only
  caught the spoilers of the systems that air English there.
* **Cut evaluations (`talkback eval --until`)** — the cut applies to every system's lines alike and the baseline is
  cached per cut; before, baseline lines past the cut were scored and a cut baseline could be reused by a full run.
* **`talkback eval-all`** — scores only broadcasts of gallery runs that completed; before, a crashed run's partial
  recording, or two runs appended to one file, could be scored.
* **Unverifiable numbers** — numbers written as words (English) are counted as numbers, for every system, with the
  same word tables Clearance uses; before, a system could keep a number out of the count by spelling it out.
* **Latency and air time** — a Talkback line's latency is measured from the moment it was spotted to the moment it
  aired, so time waiting in the queue and for the producer counts; before, it was the sum of the agents' own times,
  which left waiting out and double-counted the Archivist and the Lab, which run in parallel.

### After the first two matchdays (2026-10-27, afternoon)

Matchdays 2026 and 2027 were run and scored once; reading the flagged lines showed two defects, one in the scoring
and one in the gallery. Both are fixed, every matchday is run again on the fixed build and scored with the fixed
code, and the first recordings are kept next to the new ones (`broadcast-eval-first.jsonl`) for anyone who wants to
compare.

* **Unverifiable numbers (scoring)** — the reference set of numbers the gallery could have cited held the Stats
  Desk's event-based facts only; the tracking-based ones (top speeds, shot speeds, distances, sprints) were missing,
  so correct numbers from tracking counted as unverifiable. The reference now runs the same tracking through the same
  Stats Desk. A whole number written for a value of 10 or more that it rounds to ("123 km/h" for 122.7) is
  verifiable, as in Clearance.
* **MENA embargo (gallery)** — the territory desk judged the two-minute window on the gallery's compressed clock and
  only when the line was cleared; another match could score while a line waited to air. The window is now judged at
  the line's air time as a live broadcast would see it, and again at the moment it airs.

## Held-out matchdays: the evaluation of record (2026-10-27, before they were run)

The gallery was changed while matchdays 2026–2030 were being scored (see the amendments above), so those five are
the **development set** from here on: their results are reported, but they are not the evaluation of record. The
record is five new matchdays the system has never been run on, generated and sealed now, before any run, and played
by the build at commit `d3bf513` (or a later commit that changes no file under `src/talkback/`). Same systems,
metrics and scoring code as above; at most two matchdays play at a time.

| Seed | Key SHA-256 | Must-surface storylines |
|---|---|---|
| 2031 | `da564bdbeba1ad41fd47cc09c1b13ff8bd799a2383a5d04e2d775773a15a904e` | 9 |
| 2032 | `28c3880591d6be4b94c62c94495c01b67baafebef8d84ed0ff9a7b30ab3c7d77` | 9 |
| 2033 | `63511255a26110c38c0249bf7f1204a6f8063ce6e7c7cd14f8fa3168161fa12b` | 10 |
| 2034 | `8dbab58f1429422862370c18b67344d009803fe543f845d3155373f54562c622` | 11 |
| 2035 | `b504403f30a709570bdcefdd33b09a33e587f28de4cf1d2cebc222e7a5fd2802` | 9 |

### After the record was first scored (2026-10-27, evening)

Every line the scorer flagged on the held-out matchdays was read. All 15 numbers it counted as unverifiable for
Talkback were facts the gate had checked against their cited value, and all 6 spoilers it counted named a club of
the line's own match. Both were faults of the scorer, which applies to all three systems:

* **Club mentions** — a club counted as named when a line used any later word of its name ("Wanderers", "Town",
  "United"), which several clubs share. A club now counts only by its full name, its city or its code; a player
  still counts by surname.
* **Reference of citable numbers** — it held the shot speed of the latest shot only, sampled every five minutes, and
  judged a line against the checkpoint up to five minutes *after* it aired, when a cumulative value has already
  moved on. It now holds every player's event facts, sampled every 30 seconds, and a line is judged against the ten
  minutes before it aired and the minute after.

Everything was re-scored with the corrected code from the same saved broadcasts and cached baselines; no system was
run again. The results as first published are kept in `docs/eval-summary-as-published.json` and in `docs/PROOF.md`.
