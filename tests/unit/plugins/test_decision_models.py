"""Decision models by name through the registrar; Jev is the built-in (plugins:9.3, Requirements
58.3, 9.8)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.interfaces.decision import DecisionModel, DecisionResult
from skye.base.plugins import Registrar
from skye.models import JevDecisionModel, create_decision_model
from skye.models import plugins as _plugin


class FirstOption:
    """A third-party decision model: picks the first option with all the probability."""

    def __init__(self, bias: float = 1.0) -> None:
        self.bias = bias

    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        if not options:
            raise ValidationError("at least one option is required", "options", options)
        rest = (1.0 - self.bias) / max(len(options) - 1, 1)
        return DecisionResult(
            options[0], {o: self.bias if i == 0 else rest for i, o in enumerate(options)}
        )


@pytest.fixture
def registrar() -> Registrar:
    fresh = Registrar()
    _plugin.register(fresh)
    return fresh


def test_jev_is_a_built_in_registered_by_text(registrar):
    assert "jev" in registrar.names("provider", "decision")
    assert registrar.get("provider", "jev", "decision") is JevDecisionModel


def test_the_built_in_is_created_by_name_with_its_configuration(registrar):
    model = create_decision_model(
        "jev", registrar=registrar, endpoint="https://jev.example/decide", api_key="k", timeout=5.0
    )
    assert isinstance(model, JevDecisionModel)
    assert isinstance(model, DecisionModel)
    assert model.endpoint == "https://jev.example/decide" and model.timeout == 5.0


def test_a_bad_configuration_is_the_error_of_the_model(registrar):
    with pytest.raises(ValidationError):
        create_decision_model("jev", registrar=registrar, endpoint="")


def test_a_third_party_model_works_by_name(registrar):
    registrar.provider("first", FirstOption, function="decision")
    model = create_decision_model("first", registrar=registrar, bias=0.8)
    assert isinstance(model, DecisionModel)
    assert model.bias == 0.8  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_third_party_model_decides(registrar):
    registrar.provider("first", FirstOption, function="decision")
    result = await create_decision_model("first", registrar=registrar).decide("pick", ["a", "b"])
    assert result.choice == "a" and sum(result.probabilities.values()) == pytest.approx(1.0)


def test_a_factory_function_and_a_text_target_also_work(registrar):
    registrar.provider("factory", lambda **config: FirstOption(**config), function="decision")
    registrar.provider(
        "text",
        "skye.models.plugins.typesafe.decision:JevDecisionModel",
        replace=False,
        function="decision",
    )
    assert isinstance(create_decision_model("factory", registrar=registrar, bias=0.5), FirstOption)
    assert isinstance(
        create_decision_model("text", registrar=registrar, endpoint="https://x.example"),
        JevDecisionModel,
    )


def test_an_unknown_name_lists_the_registered_names(registrar):
    registrar.provider("first", FirstOption, function="decision")
    with pytest.raises(ConfigurationError) as caught:
        create_decision_model("nope", registrar=registrar)
    assert caught.value.details == {
        "kind": "provider",
        "name": "nope",
        "known": ["first", "jev"],
        "function": "decision",
    }


def test_a_registration_on_a_private_registrar_leaves_the_built_in_alone(registrar):
    registrar.provider("jev", FirstOption, replace=True, function="decision")
    assert isinstance(create_decision_model("jev", registrar=registrar), FirstOption)
    assert Registrar().names("provider", "decision") == []


def test_the_default_registrar_is_used_when_none_is_given(monkeypatch):
    fresh = Registrar()
    fresh.provider("first", FirstOption, function="decision")
    monkeypatch.setattr("skye.models.decision.get_registrar", lambda: fresh)
    assert isinstance(create_decision_model("first"), FirstOption)
