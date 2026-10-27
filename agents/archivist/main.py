"""Archivist: the season-storyline hunter, served as a Foundry hosted agent (A2A v1.0 on top)."""

import sys
from pathlib import Path

try:
    import hosting
except ImportError:  # running from the repo instead of the image
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
    import hosting

from talkback.gallery.agents.archivist import INSTRUCTIONS

SPEC = hosting.AgentSpec(
    name="archivist",
    description=(
        "Story hunter for a football matchday. Given a match moment and its story board, "
        "picks the season storylines worth saying now and why now."
    ),
    skills=(
        hosting.Skill(
            id="storyline-pick",
            name="Pick due storylines",
            description=(
                "Chooses which season storylines (milestones, farewells, debuts, reunions, races, "
                "relegation stakes) a moment makes worth saying, using only storyline ids from the "
                "board. Answers JSON: {storylines: [{storyline_id, why_now}]}."
            ),
            tags=("football", "storylines", "broadcast"),
        ),
    ),
    # The caller sends the story board in the prompt (moment_prompt), so the
    # tool-less fallback still answers from real data.
    fallback_instructions=INSTRUCTIONS,
)

if __name__ == "__main__":
    hosting.run(SPEC)
