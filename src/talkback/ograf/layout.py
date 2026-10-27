"""Outputs (one OGraf renderer each), the layer plan and the control token shared by the server and
the Graphics Op."""

from __future__ import annotations

import os
import secrets
from enum import IntEnum

OUTPUTS: dict[str, tuple[str, str]] = {
    "world": ("World feed", "International feed"),
    "uk": ("UK", "English-language territory feed"),
    "es": ("Spain", "Spanish-language territory feed"),
    "mena": ("MENA", "Arabic right-to-left territory feed, delayed broadcast"),
    "kids": ("Kids", "Minors-safe English feed"),
    "br": ("Brazil", "Portuguese-language territory feed"),
    "presenter": ("Presenter", "Talkback cue strip for the presenter, never composited to air"),
}
PRESENTER = "presenter"


class Layer(IntEnum):
    BUG = 10
    TAG = 20
    LOWER = 30
    CARD = 40
    IFB = 50


LAYERS: dict[Layer, tuple[str, str]] = {
    Layer.BUG: ("Bug", "Scorebug"),
    Layer.TAG: ("Tag", "Player tags over the pitch"),
    Layer.LOWER: ("Lower", "Lower thirds and story cards"),
    Layer.CARD: ("Card", "Stat, counterfactual and table-swing cards"),
    Layer.IFB: ("IFB", "Presenter cue strip"),
}


def render_target(layer: int) -> dict[str, int]:
    return {"layer": int(layer)}


TOKEN_ENV = "TALKBACK_OGRAF_TOKEN"
_TOKEN: str | None = None


def control_token() -> str:
    """The bearer token for Server API calls that change graphics: TALKBACK_OGRAF_TOKEN, or else one
    made once per process, which the in-process Graphics Op uses too."""
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(32)
    return _TOKEN
