"""The Clearance gate: universal checks once, then every territory desk in parallel.

Verdicts only get more severe (ON_AIR < HOLD_FOR_PRODUCER < KILLED) and reasons
accumulate. Any exception or timeout kills: one territory if it happens at that
desk, every territory if it happens before the fan-out.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from talkback.clearance.checks import (
    CheckContext, check_causal, check_numbers, check_strength, universal_checks, worst,
)
from talkback.clearance.lexicon import base_lang
from talkback.clearance.packs import ClearancePack, PackContext, apply_pack
from talkback.clearance.safety import ContentSafety
from talkback.clearance.sensitive import LANGS as SENSITIVE_LANGS
from talkback.clearance.sensitive import sensitive_topics
from talkback.schemas.models import Cue, TerritoryVerdict, Verdict

Localized = dict[str, tuple[str, str]]


class Gate:
    def __init__(self, packs: dict[str, ClearancePack], safety: ContentSafety,
                 safety_timeout_s: float = 5.0) -> None:
        self.packs = packs
        self.safety = safety
        self.safety_timeout_s = safety_timeout_s

    async def evaluate(self, cue: Cue, check_ctx: CheckContext, localized: Localized,
                       pack_ctx: PackContext) -> Cue:
        """Fill `cue.universal_reasons` and `cue.verdicts`; `localized` maps territory -> (text, lang)."""
        territories = sorted(self.packs)
        try:
            territories = sorted({*self.packs, *localized})
            verdict, reasons = universal_checks(cue, check_ctx)
            if verdict is Verdict.KILLED:
                results = [self._killed(t, cue, localized, reasons) for t in territories]
            else:
                results = await asyncio.gather(*(
                    self._desk(t, cue, check_ctx, localized, pack_ctx, verdict, reasons)
                    for t in territories))
        except Exception as exc:
            reasons = [f"error: {type(exc).__name__}"]
            results = [self._killed(t, cue, localized, reasons) for t in territories]
        cue.universal_reasons = list(reasons)
        cue.verdicts = {r.territory: r for r in results}
        return cue

    @staticmethod
    def _killed(territory: str, cue: Cue, localized: Localized,
                reasons: list[str]) -> TerritoryVerdict:
        try:
            text = str(localized[territory][0])
        except Exception:
            text = cue.text
        return TerritoryVerdict(territory=territory, verdict=Verdict.KILLED, reasons=list(reasons),
                                text=text)

    async def _desk(self, territory: str, cue: Cue, check_ctx: CheckContext, localized: Localized,
                    pack_ctx: PackContext, verdict: Verdict,
                    reasons: list[str]) -> TerritoryVerdict:
        try:
            pack = self.packs.get(territory)
            if pack is None:
                return self._killed(territory, cue, localized,
                                    [f"pack: no clearance pack for '{territory}'"])
            if territory in localized:
                text, lang = localized[territory]
            elif base_lang(cue.lang) in pack.langs:
                text, lang = cue.text, cue.lang
            else:
                return self._killed(territory, cue, localized,
                                    [f"localisation: no {'/'.join(pack.langs)} text"])
            if base_lang(lang) not in pack.langs:
                return self._killed(territory, cue, localized,
                                    [f"localisation: '{lang}' is not a {territory} language"])
            reasons = list(reasons)
            local_cue = cue.model_copy(update={"text": text})
            local_ctx = replace(check_ctx, lang=lang)
            recheck = [*check_numbers(local_cue, local_ctx), *check_strength(local_cue, local_ctx),
                       *check_causal(local_cue, local_ctx)]
            if recheck:
                verdict = Verdict.KILLED
                reasons += recheck
            if text != cue.text and base_lang(lang) in SENSITIVE_LANGS:
                # a translation can name what the source only hinted at
                added = [r for r in (f"sensitive: {t}" for t in sorted(sensitive_topics(text, lang)))
                         if r not in reasons]
                if added:
                    verdict = worst(verdict, Verdict.HOLD_FOR_PRODUCER)
                    reasons += added
            ok, note = await asyncio.wait_for(self.safety.analyze(text), self.safety_timeout_s)
            if not ok:
                verdict = Verdict.KILLED
                reasons.append(note or "content-safety: rejected")
            desk = apply_pack(pack, text, lang, cue, pack_ctx)
            return TerritoryVerdict(territory=territory, verdict=worst(verdict, desk.verdict),
                                    reasons=list(dict.fromkeys(reasons + desk.reasons)), text=text)
        except Exception as exc:
            return self._killed(territory, cue, localized, [f"error: {type(exc).__name__}"])
