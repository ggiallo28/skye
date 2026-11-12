"""Jev behind the ``DecisionModel`` Port: a closed choice with well-formed probabilities (task 7)."""

from __future__ import annotations

import asyncio
import json
import math
import random
from typing import Any
from unittest.mock import patch

import pytest

from skye.base.exceptions import ProviderError, SkyeError, ValidationError
from skye.base.interfaces.decision import DecisionModel, DecisionResult
from skye.models import JevDecisionModel
from skye.models.plugins.typesafe.decision import normalize_probabilities
from tests.examples.fake_network import FakeResponse


def _serving(body: Any, seen: list[Any] | None = None):
    def urlopen(req: Any, timeout: float | None = None, **_: Any) -> FakeResponse:
        if seen is not None:
            seen.append((req.full_url, json.loads(req.data), {k.lower(): v for k, v in req.header_items()}))
        return FakeResponse(json.dumps(body).encode())

    return patch("urllib.request.urlopen", urlopen)


def _decide(model: JevDecisionModel, options: list[str], prompt: str = "q") -> DecisionResult:
    return asyncio.run(model.decide(prompt, options))


def test_it_implements_the_port():
    assert isinstance(JevDecisionModel(endpoint="http://x"), DecisionModel)


def test_it_sends_the_prompt_and_options_and_returns_the_most_probable_option():
    seen: list[Any] = []
    model = JevDecisionModel(endpoint="http://jev.local/decide", api_key="k")
    with _serving({"probabilities": {"yes": 0.2, "no": 0.8}}, seen):
        result = _decide(model, ["yes", "no"], "Is it risky?")
    assert result.choice == "no"
    assert result.probabilities == {"yes": 0.2, "no": 0.8}
    url, body, headers = seen[0]
    assert url == "http://jev.local/decide"
    assert body == {"prompt": "Is it risky?", "options": ["yes", "no"]}
    assert headers["authorization"] == "Bearer k"


def test_a_list_of_probabilities_follows_the_order_of_the_options():
    with _serving({"probabilities": [0.1, 0.6, 0.3]}):
        result = _decide(JevDecisionModel(endpoint="http://x"), ["a", "b", "c"])
    assert result.choice == "b"


def test_probabilities_that_do_not_sum_to_one_are_scaled():
    with _serving({"probabilities": {"a": 0.2, "b": 0.2}}):
        result = _decide(JevDecisionModel(endpoint="http://x"), ["a", "b"])
    assert result.probabilities == {"a": 0.5, "b": 0.5}
    assert result.choice == "a"  # a tie keeps the first option


def test_an_empty_option_set_is_rejected_and_nothing_is_sent():
    seen: list[Any] = []
    with _serving({"probabilities": {}}, seen), pytest.raises(ValidationError):
        _decide(JevDecisionModel(endpoint="http://x"), [])
    assert seen == []


@pytest.mark.parametrize("options", [["a", "a"], ["a", ""], "ab"])
def test_malformed_options_are_rejected(options):
    with pytest.raises(ValidationError):
        _decide(JevDecisionModel(endpoint="http://x"), options)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"probabilities": {"a": 1.0}},  # b missing
        {"probabilities": {"a": 1.5, "b": -0.5}},
        {"probabilities": {"a": "x", "b": 0.5}},
        {"probabilities": {"a": 0, "b": 0}},
        {"probabilities": [1.0]},
    ],
)
def test_a_malformed_answer_raises_a_provider_error_and_no_choice(body):
    with _serving(body), pytest.raises(ProviderError):
        _decide(JevDecisionModel(endpoint="http://x"), ["a", "b"])


def test_probabilities_are_well_formed_for_any_non_empty_option_set():
    """Property: each probability is in 0..1 and they sum to 1, whatever positive weights the endpoint returns."""
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(1, 12)
        options = [f"o{i}" for i in range(n)]
        raw = {o: rng.random() for o in options}
        if not any(raw.values()):
            raw[options[0]] = 0.5
        out = normalize_probabilities(options, raw)
        assert list(out) == options
        assert all(0.0 <= p <= 1.0 for p in out.values())
        assert math.isclose(sum(out.values()), 1.0, abs_tol=1e-9)
        chosen = max(options, key=lambda o: out[o])
        assert out[chosen] == max(out.values())


def test_an_error_is_a_skye_error():
    assert issubclass(ProviderError, SkyeError) and issubclass(ValidationError, SkyeError)
