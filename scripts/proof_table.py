"""Render the evaluation summary (talkback eval-all --out) as the Markdown table in docs/PROOF.md.

    uv run python scripts/proof_table.py docs/eval-summary.json docs/PROOF.md
"""

import json
import sys
from pathlib import Path

MARK = "<!-- EVAL-RESULTS -->"
SYSTEMS = [("talkback", "Talkback"), ("baseline", "Single model"), ("talkback_without_clearance", "Clearance off")]
ROWS = [
    ("Story Recall (must-surface storylines on air in time)", lambda r: f"**{r['story_recall']:.0%}** "
                                                                       f"({r['stories_hit']}/{r['must']})"),
    ("…surfaced late / missed", lambda r: f"{r['stories_late']} / {r['stories_missed']}"),
    ("Unverifiable numbers on air", lambda r: f"{r['unverifiable_rate']:.1%} ({r['unverifiable_numbers']}/{r['numbers']})"),
    ("Over-claims in the first 8 minutes", lambda r: str(r["overclaims_in_thin_windows"])),
    ("Spoilers inside MENA's two-minute delay", lambda r: str(r["mena_spoilers"])),
    ("Trivia that reached air", lambda r: str(r["trivia_intrusions"])),
    ("Lines on air (English)", lambda r: str(r["lines"])),
]


def table(summary: dict) -> str:
    systems = summary["systems"]
    head = "| | " + " | ".join(label for key, label in SYSTEMS if key in systems) + " |"
    sep = "|---|" + "---|" * sum(1 for key, _ in SYSTEMS if key in systems)
    body = [f"| {name} | " + " | ".join(fmt(systems[key]) for key, _ in SYSTEMS if key in systems) + " |"
            for name, fmt in ROWS]
    days = summary.get("matchdays", [])
    keys = ", ".join(f"`{m.get('key_sha256', '')[:12]}…`" for m in days)
    return "\n".join([f"{len(days)} matchdays, 10 matches each; sealed keys {keys}", "", head, sep, *body])


def main(summary_path: str, proof_path: str) -> None:
    proof = Path(proof_path)
    text = proof.read_text(encoding="utf-8")
    start = text.index(MARK)
    end = text.find(MARK, start + len(MARK))
    block = f"{MARK}\n{table(json.loads(Path(summary_path).read_text(encoding='utf-8')))}\n{MARK}"
    text = text[:start] + block + (text[end + len(MARK):] if end != -1 else text[start + len(MARK):])
    proof.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
