import asyncio

import talkback.mcp.server as m

STATE = [
    {"kind": "score", "sim_t": 600_000, "data": {"match_id": "MD12-F01", "score": [1, 0], "minute": 10}},
    {"kind": "aired", "sim_t": 600_000, "data": {"match_id": "MD12-F01", "territory": "uk", "text": "First goal.",
                                                 "cue_id": "Q-1"}},
    {"kind": "aired", "sim_t": 650_000, "data": {"match_id": "MD12-F01", "territory": "es", "text": "Primer gol.",
                                                 "cue_id": "Q-1"}},
    {"kind": "cue", "sim_t": 660_000, "data": {"id": "Q-2", "match_id": "MD12-F01", "text": "They are dominant.",
                                               "verdicts": {"uk": {"verdict": "KILLED", "reasons": ["strength: x"]},
                                                            "es": {"verdict": "ON_AIR", "reasons": []}}}},
]


def _patch(monkeypatch):
    async def fake_state():
        return STATE
    monkeypatch.setattr(m, "_state", fake_state)


def test_aired_lines_filters_by_territory(monkeypatch):
    _patch(monkeypatch)
    rows = asyncio.run(m.aired_lines(match_id="MD12-F01", territory="uk"))
    assert [r["text"] for r in rows] == ["First goal."] and rows[0]["minute"] == 10


def test_refused_lines_report_reasons(monkeypatch):
    _patch(monkeypatch)
    rows = asyncio.run(m.refused_lines())
    assert rows[0]["cue_id"] == "Q-2" and rows[0]["refused"]["uk"]["reasons"] == ["strength: x"]
    assert "es" not in rows[0]["refused"]


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(m.server.list_tools())}
    assert {"list_matches", "aired_lines", "refused_lines", "story_board", "live_table", "explain_line"} <= names
