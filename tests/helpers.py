"""Shared test helpers (imported by the test modules).

Tests never touch the network: sources get an httpx.Client whose transport is a
function returning canned responses. The Merriam-Webster and Free Dictionary
fixtures are trimmed examples in each API's documented format; the Wiktionary
fixture is a real response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Recorder:
    """Routes requests to a handler and remembers them for assertions."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

