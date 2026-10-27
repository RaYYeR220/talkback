import asyncio

import pytest
from agent_framework import Agent
from pydantic import BaseModel

from talkback.gallery.jsonio import ParseError, parse_json
from talkback.gallery.llm import ScriptedClient, message_text


class Pick(BaseModel):
    storyline_id: str
    why_now: str


def test_agent_with_scripted_client_returns_parsed_model():
    client = ScriptedClient(lambda msgs: '```json\n{"storyline_id": "S-1", "why_now": "on 99"}\n```')
    agent = Agent(client=client, instructions="Return JSON.", name="probe")
    result = asyncio.run(agent.run("which story?"))
    pick = parse_json(result.text, Pick)
    assert pick.storyline_id == "S-1"
    assert client.calls == 1


def test_script_sees_the_prompt():
    seen = []
    client = ScriptedClient(lambda msgs: (seen.append(message_text(msgs)), '{"storyline_id":"x","why_now":"y"}')[1])
    asyncio.run(Agent(client=client, instructions="Be brief.").run("Calder Vale lead"))
    assert "Calder Vale lead" in seen[0]


def test_prose_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_json("Sure! The best story is the milestone.", Pick)


def test_wrong_shape_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_json('{"storyline": "S-1"}', Pick)


def test_braces_inside_strings():
    p = parse_json('noise {"storyline_id": "S-{1}", "why_now": "a } b"} trailing', Pick)
    assert p.storyline_id == "S-{1}"
