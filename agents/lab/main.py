"""Lab: counterfactual replays that earn causal wording, served as a Foundry hosted agent (A2A v1.0 on top)."""

import sys
from pathlib import Path

try:
    import hosting
except ImportError:  # running from the repo instead of the image
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
    import hosting

# Without the simulator tools (talkback.hosted.lab) the Lab must never support
# a causal claim, so the fallback always reports no clear effect.
FALLBACK = (
    "You are the Lab in a football production gallery. The match simulator is not available "
    "in this deployment, so you cannot run experiments. Whatever you are asked, answer only "
    'with this JSON: {"experiments": [], "conclusion": "no clear effect", "supported": false}'
)

SPEC = hosting.AgentSpec(
    name="lab",
    description=(
        "Evidence supplier for causal claims. Replays a match moment in the simulator with one "
        "thing changed and reports the effect with a 95% interval."
    ),
    skills=(
        hosting.Skill(
            id="counterfactual",
            name="Counterfactual replay",
            description=(
                "Runs typed interventions (flip an event, shift a position, keep the press or line) "
                "over batched rollouts. A causal claim is supported only when the 95% interval of the "
                "paired effect excludes zero. Answers JSON: {experiments, conclusion, supported}."
            ),
            tags=("football", "simulation", "causal"),
        ),
    ),
    fallback_instructions=FALLBACK,
)

if __name__ == "__main__":
    hosting.run(SPEC)
