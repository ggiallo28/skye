"""Decision models by name: ``create_decision_model`` reads the registrar (Requirement 58.3, plugins:9.3).

Jev is registered as the built-in ``"jev"`` by ``skye.models.plugins``. A third party adds its own with
``registrar.provider(name, target, function="decision")``, where ``target`` is a class or a factory that takes the configuration as keyword arguments
(or a ``"module:attribute"`` text for it).

Raises: ``ConfigurationError`` for an unknown name (the error lists the registered names) or a target that does not import; whatever the
    target raises for a bad configuration (``JevDecisionModel`` raises ``ValidationError`` for a missing endpoint).
Missing: there is no default name: the caller names the model.
Concurrency: a lookup reads an in-memory table; the model it returns is built per call and is not shared.
"""

from __future__ import annotations

from typing import Any

from skye.base.interfaces.decision import DecisionModel
from skye.base.plugins import Registrar, get_registrar


def create_decision_model(
    name: str, *, registrar: Registrar | None = None, **config: Any
) -> DecisionModel:
    """Build the decision model registered under ``name``, passing ``config`` to its class or factory.

    Args:
        name: The registered name, for example ``"jev"``.
        registrar: The registrar to read; the default registrar of the process when omitted.
        **config: Keyword arguments for the class or factory, for example ``endpoint=...`` for Jev.

    Returns:
        A ``DecisionModel``.

    Raises:
        ConfigurationError: ``name`` is not registered, or its text target cannot be imported.
    """
    target = (registrar or get_registrar()).get("provider", name, "decision")
    model: DecisionModel = target(**config)
    return model
