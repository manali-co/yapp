"""Thin typed wrapper over the TypeSafe SDK. The only module that talks to the API."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from typesafe_sdk import (
    Question,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeClient,
    TypeSafeError,
)


class JevError(Exception):
    """Any failure talking to Jev. A failed call never executes anything."""


@dataclass(frozen=True)
class ChoiceResult:
    key: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class JevResponse:
    raw: dict[str, Any]
    latency_ms: int
    input_tokens: int
    resp: SystemOneResponse

    def choice(self, name: str) -> ChoiceResult:
        a = self.resp.choices[name]
        return ChoiceResult(a.choice, a.confidence, dict(a.probabilities))

    def noul(self, name: str) -> float:
        return self.resp.nouls[name].noul


class JevLike(Protocol):
    """Anything that answers like Jev: the real client, or a counting/recording wrapper."""

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> JevResponse: ...


class Jev:
    def __init__(self, client: TypeSafeClient | None = None, *, model: str) -> None:
        if client is None:
            if not os.environ.get("TYPESAFE_API_KEY"):
                raise JevError("TYPESAFE_API_KEY is not set")
            client = TypeSafeClient(model=model, retry=RetryPolicy(max_retries=1), timeout=5.0)
        self._client = client
        self._model = model

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> JevResponse:
        started = time.perf_counter()
        try:
            resp = self._client.system_one(dict(state), questions, model=self._model)
        except TypeSafeError as e:
            raise JevError(str(e)) from e
        latency = int((time.perf_counter() - started) * 1000)
        return JevResponse(
            raw=resp.model_dump(),
            latency_ms=latency,
            input_tokens=resp.usage.input_tokens or 0,
            resp=resp,
        )
