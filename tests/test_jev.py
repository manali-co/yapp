import json

import httpx2 as httpx
import pytest
from typesafe_sdk import Choice, Noul, TypeSafeClient

from yapp.jev import Jev, JevError

CANNED = {
    "model": "jev-1.13.0",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "open_app",
            "confidence": 0.9,
            "probabilities": {"open_app": 0.93, "none": 0.07},
        },
        "is_complete": {"type": "noul", "noul": 0.88},
    },
    "usage": {"input_tokens": 120, "output_tokens": 10},
}


def make_jev(handler: httpx.MockTransport) -> Jev:
    client = TypeSafeClient(api_key="test", model="jev-1.13.0", transport=handler)
    return Jev(client, model="jev-1.13.0")


def test_ask_parses_choice_and_noul() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CANNED)

    jev = make_jev(httpx.MockTransport(handler))
    resp = jev.ask(
        {"instruction_so_far": "open notes"},
        {
            "intent": Choice(instructions="?", criteria={"open_app": "x", "none": "y"}),
            "is_complete": Noul(instructions="?"),
        },
    )
    assert resp.choice("intent").key == "open_app"
    assert resp.choice("intent").confidence == 0.9
    assert resp.choice("intent").probabilities["none"] == 0.07
    assert resp.noul("is_complete") == 0.88
    assert resp.input_tokens == 120
    assert seen["body"]["model"] == "jev-1.13.0"  # type: ignore[index]


def test_api_error_becomes_jev_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    jev = make_jev(httpx.MockTransport(handler))
    with pytest.raises(JevError):
        jev.ask({"instruction_so_far": "x"}, {"q": Noul(instructions="?")})
