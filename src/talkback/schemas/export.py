"""Write the JSON Schema of every shared model, for integrators."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from talkback.schemas.models import ALL_MODELS, ClaimKind, EventType, Outcome, Verdict

ENUMS = [EventType, Outcome, Verdict, ClaimKind]


def export_schemas(out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in ALL_MODELS:
        written.append(_write(out_dir / f"{model.__name__}.schema.json", model.model_json_schema()))
    for enum in ENUMS:
        written.append(_write(out_dir / f"{enum.__name__}.schema.json", TypeAdapter(enum).json_schema()))
    return written


def _write(path: Path, schema: dict) -> Path:
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    for p in export_schemas(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/schemas")):
        print(p)
