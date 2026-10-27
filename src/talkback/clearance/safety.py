"""Content Safety interface, plus a dev stand-in that refuses to run outside dev."""

from __future__ import annotations

import os
from typing import Protocol


class ContentSafety(Protocol):
    async def analyze(self, text: str) -> tuple[bool, str]:
        """(allowed, note). Raising or timing out counts as not allowed."""
        ...


class LocalDevSafety:
    """Skips Content Safety. Only constructible with TALKBACK_ENV=dev."""

    def __init__(self) -> None:
        if os.environ.get("TALKBACK_ENV") != "dev":
            raise RuntimeError("LocalDevSafety skips Content Safety; it needs TALKBACK_ENV=dev")

    async def analyze(self, text: str) -> tuple[bool, str]:
        return True, "content-safety: skipped (dev)"
