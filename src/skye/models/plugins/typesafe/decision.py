"""Jev, a decision model: a state and a finite set of options in, one choice with a probability per option out.

Jev (from TypeSafe AI, https://typesafe.ai/, a "System One" model) does not write text. It answers a closed question, so the result is cheap, fast and
checkable. This adapter implements the ``DecisionModel`` Port over the standard-library REST transport; it needs no extra.

Wire format. The request is a JSON ``POST`` to ``endpoint`` with ``{"prompt": <text>, "options": [<option>, ...]}`` and an
optional bearer key. The response is a JSON object whose ``probabilities`` is either an object ``{option: probability}`` or a
list of probabilities in the order of ``options``. This is the shape the library agreed with its consumers (the ``gateway``
selector reaches any endpoint that speaks it, a local Jev included); it has not been checked against a hosted Jev service (the announcement at
https://typesafe.ai/blog/introducing-system-one-models-and-jev publishes the price, 0.042 USD per million input tokens with output free, but no endpoint or
schema; the documentation is at docs.typesafe.ai), so
subclass :meth:`JevDecisionModel._build_request` and :meth:`JevDecisionModel._read_probabilities` to adapt another shape.

Whatever the endpoint returns is validated here, once: every option has a probability in 0..1, the probabilities are scaled to
sum to 1, and the choice is the most probable option (the first one on a tie). An empty option set raises ``ValidationError``
and nothing is sent.

Example:
    >>> model = JevDecisionModel(endpoint="http://localhost:8080/decide")
    >>> result = await model.decide("Is this action risky?", ["yes", "no"])  # doctest: +SKIP
    >>> result.choice, result.probabilities  # doctest: +SKIP
    ('no', {'yes': 0.12, 'no': 0.88})
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from typing import Any

from skye.base.exceptions import ProviderError, ValidationError
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.base.interfaces.decision import DecisionResult
from skye.models.utilities.rest import post_json

_SUM_TOLERANCE = 1e-6


def normalize_probabilities(options: Sequence[str], raw: Any) -> dict[str, float]:
    """Check an endpoint's probabilities against ``options`` and scale them to sum to 1.

    ``raw`` is an object ``{option: probability}`` or a list in the order of ``options``. Raises ``ProviderError`` when an option
    has no probability, a value is not a finite number in 0..1, or all are zero.
    """
    if isinstance(raw, Mapping):
        missing = [o for o in options if o not in raw]
        if missing:
            raise ProviderError(
                f"The decision model gave no probability for {missing}", provider="jev"
            )
        values = [raw[o] for o in options]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        if len(raw) != len(options):
            raise ProviderError(
                f"The decision model gave {len(raw)} probabilities for {len(options)} options",
                provider="jev",
            )
        values = list(raw)
    else:
        raise ProviderError("The decision model returned no probabilities", provider="jev")

    numbers: list[float] = []
    for option, value in zip(options, values):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ProviderError(
                f"The probability of {option!r} is not a number in 0..1: {value!r}", provider="jev"
            )
        numbers.append(float(value))
    total = sum(numbers)
    if total <= 0:
        raise ProviderError(
            "The decision model gave every option a probability of zero", provider="jev"
        )
    if abs(total - 1.0) > _SUM_TOLERANCE:
        numbers = [n / total for n in numbers]
    return dict(zip(options, numbers))


def _check_options(options: Sequence[str]) -> list[str]:
    if isinstance(options, (str, bytes)) or not isinstance(options, Sequence):
        raise ValidationError("options must be a sequence of strings", "options", options)
    checked = list(options)
    if not checked:
        raise ValidationError("at least one option is required", "options", checked)
    for option in checked:
        if not isinstance(option, str) or not option:
            raise ValidationError("every option must be a non-empty string", "options", option)
    if len(set(checked)) != len(checked):
        raise ValidationError("options must be distinct", "options", checked)
    return checked


class JevDecisionModel:
    """``DecisionModel`` backed by a Jev endpoint over the built-in REST transport.

    Args:
        endpoint: URL that receives the decision request (a hosted or a local Jev).
        api_key: Optional bearer key. No environment variable is read: the library owns only three ``SKYE_*`` variables (D18).
        authenticator: Optional ``AuthenticationInterface`` that signs the request instead of a bearer key.
        timeout: Seconds to wait for the endpoint.
    """

    provider_name = "jev"

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        authenticator: AuthenticationInterface | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not endpoint:
            raise ValidationError("endpoint is required", "endpoint", endpoint)
        self.endpoint = endpoint
        self._api_key = api_key
        self._authenticator = authenticator
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"JevDecisionModel(endpoint={self.endpoint!r})"

    def _build_request(self, prompt: str, options: list[str]) -> dict[str, Any]:
        return {"prompt": prompt, "options": options}

    def _read_probabilities(self, response: Any) -> Any:
        data = response.to_dict() if hasattr(response, "to_dict") else response
        return data.get("probabilities") if isinstance(data, Mapping) else None

    def decide_sync(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        """Blocking form of :meth:`decide`."""
        checked = _check_options(options)
        headers = (
            {"Authorization": f"Bearer {self._api_key}"}
            if self._api_key and self._authenticator is None
            else None
        )
        response = post_json(
            self.endpoint,
            self._build_request(prompt, checked),
            headers=headers,
            authenticator=self._authenticator,
            timeout=self.timeout,
            provider=self.provider_name,
        )
        probabilities = normalize_probabilities(checked, self._read_probabilities(response))
        choice = max(
            checked, key=lambda option: probabilities[option]
        )  # max keeps the first of equal values
        return DecisionResult(choice=choice, probabilities=probabilities)

    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        """Pick one of ``options`` for ``prompt``; raises ``ValidationError`` when ``options`` is empty."""
        _check_options(options)
        return await asyncio.get_running_loop().run_in_executor(
            None, self.decide_sync, prompt, options
        )


__all__ = ["JevDecisionModel", "normalize_probabilities"]
