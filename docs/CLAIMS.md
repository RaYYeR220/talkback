# What we claim, and how you can check it

Every public statement about Talkback, tagged by the kind of evidence behind it.

* **REPRODUCIBLE** — run the command and get the same result.
* **VERIFIED-LIVE** — visible in the deployed gallery or the Azure resources.
* **MEASURED** — produced by the pre-registered evaluation; numbers in [PROOF.md](PROOF.md).
* **NOT CLAIMED** — we do not claim this.

| Claim | Evidence | How to check |
|---|---|---|
| The match engine reproduces public league averages for goals, shots, shots on target, passes, completion, PPDA, fouls, corners, cards and distance | REPRODUCIBLE | `uv run python -m talkback.sim.calibrate --n 500` → [calibration.md](calibration.md) |
| Every match is deterministic from (fixture, seed) and can be restored from a snapshot | REPRODUCIBLE | `tests/sim/test_engine.py` (`test_deterministic`, `test_snapshot_restore`) |
| Storylines are planted in the data and the must-surface key is sealed before evaluation | REPRODUCIBLE | `talkback matchday --seed 2026` writes `key.sha256`; hashes in [preregistration.md](preregistration.md) |
| The gallery never sees planted storylines; it finds them in raw season data | REPRODUCIBLE | `world.json` has no storylines (`tests/world/test_matchday.py`); miners in `src/talkback/gallery/miners.py` |
| Every number on air cites a Fact, Experiment or Storyline with that value and that subject | REPRODUCIBLE | `src/talkback/clearance/checks.py`; `tests/clearance/test_checks.py` (`test_misattribution_killed`, `test_number_without_claim_killed`) |
| Wording strength is checked against sample size, window and effect | REPRODUCIBLE | `tests/clearance/test_checks.py::test_strength_thin_evidence` |
| Causal words need a counterfactual experiment whose 95% interval excludes zero | REPRODUCIBLE | `tests/clearance/test_checks.py::test_causal_requires_supported_experiment`; `tests/sim/test_rollout.py` |
| The same line can air in one territory, be held in another and be killed in a third | REPRODUCIBLE | `tests/clearance/test_packs.py::test_matrix` |
| Any error, timeout or malformed model output is a refusal | REPRODUCIBLE | `tests/clearance/test_checks.py::test_fail_closed`; `tests/gallery/test_workflow.py` |
| Producer holds pause the workflow and resume on the decision; silence expires as not aired | REPRODUCIBLE | `tests/gallery/test_workflow.py` |
| A failing Lab or Archivist degrades the moment instead of stopping it | REPRODUCIBLE | `tests/gallery/test_workflow.py::test_lab_failure_degrades_but_moment_still_airs` |
| The Archivist and the Lab answer over A2A v1.0 and fall back in process | REPRODUCIBLE locally, VERIFIED-LIVE as Foundry hosted agents | `tests/gallery/test_a2a.py`; agent cards in the Foundry project |
| Graphics go to air through the EBU OGraf v1 Server API | REPRODUCIBLE | `tests/ograf/`; `/ograf/v1` and `/ograf/renderer/?renderer=uk` on the live service |
| Story Recall, unverifiable numbers, over-claims and spoilers compared with a single model on the same data | MEASURED | [PROOF.md](PROOF.md) |
| The deployment runs on Azure Container Apps, Event Hubs, Cosmos DB, Blob Storage, Content Safety, Application Insights and Foundry | VERIFIED-LIVE | `infra/`, `azure.yaml`, the live URLs in [JUDGES.md](JUDGES.md) |
| Real clubs, players or match data are used | NOT CLAIMED — none are used | `src/talkback/world/names.py` (`BANNED_CLUB_NAMES` is asserted against) |
| Auto-eventing from video | NOT CLAIMED | — |
| Microsoft Fabric, Teams / Microsoft 365 publishing | NOT CLAIMED | — |
| The territory packs are legal advice | NOT CLAIMED — illustrative editorial templates | `src/talkback/clearance/packs/*.yaml` (`disclaimer`) |
