"""Outputs (one OGraf renderer each) and the layer plan shared by the server and the Graphics Op."""

from __future__ import annotations

from enum import IntEnum

OUTPUTS: dict[str, tuple[str, str]] = {
    "world": ("World feed", "International feed"),
    "uk": ("UK", "English-language territory feed"),
    "es": ("Spain", "Spanish-language territory feed"),
    "mena": ("MENA", "Arabic right-to-left territory feed, delayed broadcast"),
    "kids": ("Kids", "Minors-safe English feed"),
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
