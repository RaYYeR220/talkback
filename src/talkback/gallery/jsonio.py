"""Strict parsing of model output into pydantic models (no repair, no fallback text)."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ParseError(Exception):
    """The model's answer could not be read as the expected JSON."""


def _first_json(text: str) -> str:
    text = _FENCE.sub("", text.strip())
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ParseError("no JSON object in model output")
    start = min(starts)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ParseError("unterminated JSON in model output")


def parse_json(text: str, model: type[M]) -> M:
    try:
        return model.model_validate(json.loads(_first_json(text)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ParseError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
