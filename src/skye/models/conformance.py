# Requirement 58.4, D98, D111
"""``check_provider`` and ``check_tokenizer``: the conformance functions of the kinds that
``models`` owns.

Both run offline and return the names of the checks they passed; the first check that fails raises
an ``AssertionError`` that names it
(``skye.store.check_backend`` is the model). Both are coroutine functions, so one runner awaits
every kind alike.

Example:
    >>> import asyncio
    >>> from skye.models.conformance import check_tokenizer
    >>> class Words:
    ...     def encode(self, text):
    ...         return text.split()
    >>> asyncio.run(check_tokenizer(Words()))
    ['resolves', 'encodes', 'empty', 'repeatable']

Raises: ``AssertionError`` naming the first failed check.
Missing: ``check_provider`` checks the class alone; it builds one only when ``config`` is given, so
a provider that needs a key or a network is
    checked by its shape (give it ``config`` with a fake to check the object too).
Concurrency: nothing is shared; each call builds its own objects.
"""

from __future__ import annotations

from typing import Any

from skye.base.conformance import Check, require, run_checks
from skye.base.plugins import PROVIDER_FUNCTIONS, _functions_of, get_registrar

_ASYNC_METHODS = {
    "model": ("acomplete", "astream"),
    "embedding": ("aencode", "aencode_batch"),
    "decision": ("decide",),
}


def _has_method(provider: Any, method: str) -> Check:
    return (
        method,
        lambda: require(
            callable(getattr(provider, method, None)), f"the provider has no method {method!r}"
        ),
    )


# Requirement 9.8
async def _decision_rule(instance: Any) -> None:
    """One of the options, a probability each in 0 to 1 summing to 1, an error for no options."""
    options = ["a", "b", "c"]
    result = await instance.decide("pick one", options)
    probabilities = dict(result.probabilities)
    require(result.choice in options, f"the choice {result.choice!r} is not one of the options")
    require(
        all(0.0 <= value <= 1.0 for value in probabilities.values()),
        "a probability is outside 0 to 1",
    )
    require(
        not probabilities or abs(sum(probabilities.values()) - 1.0) < 1e-6,
        "the probabilities do not sum to 1",
    )
    try:
        await instance.decide("pick one", [])
    except Exception:
        return
    raise AssertionError("an empty set of options must raise an error and return no choice")


async def check_provider(
    provider: Any,
    *,
    name: str | None = None,
    function: str | None = None,
    config: dict[str, Any] | None = None,
    registrar: Any = None,
) -> list[str]:
    """Check a provider class: the function it has, the methods of that function, the profile and,
    with ``config``, an object built from it.

    Args:
        provider: The class (or object) registered as a ``provider``.
        name: The registered name; when given, the provider must have a profile in the registrar.
        function: ``"model"``, ``"embedding"`` or ``"decision"``; inferred from the methods when
            omitted.
        config: When given, the class is built with it and the object is checked
            (``get_model_info``, the vector dimension, or the rule of a
            decision).
        registrar: Where the profile is read from; the default registrar when omitted.

    Returns:
        The names of the checks that passed.
    """
    shown = [function] if function else _functions_of(provider)
    chosen = shown[0] if len(shown) == 1 else None
    checks: list[Check] = [
        (
            "function",
            lambda: require(
                chosen in PROVIDER_FUNCTIONS,
                f"the functions are {shown or 'none'}; it is one of "
                f"{', '.join(PROVIDER_FUNCTIONS)} (give function=)",
            ),
        )
    ]
    if chosen is not None:
        checks += [_has_method(provider, method) for method in _ASYNC_METHODS[chosen]]
        if chosen == "embedding":
            checks.append(_has_method(provider, "get_vector_dimension"))
    if name is not None:
        profile = (registrar or get_registrar()).get_profile
        checks.append(("profile", lambda: require(profile(name), f"no profile for {name!r}")))
    if config is not None and chosen is not None:
        function_name, built = chosen, list[Any]()
        checks.append(("builds", lambda: built.append(provider(**config))))
        checks.append(("object", lambda: _object(function_name, built[0])))
    return await run_checks("provider", provider, checks)


def _object(function: str, instance: Any) -> Any:
    if function == "model":
        return require(
            isinstance(instance.get_model_info(), dict), "get_model_info must return a dict"
        )
    if function == "embedding":
        size = instance.get_vector_dimension()
        return require(
            isinstance(size, int) and size > 0, "the vector dimension must be a positive int"
        )
    return _decision_rule(instance)


async def check_tokenizer(tokenizer: Any, model: str = "model") -> list[str]:
    """Check a tokenizer: an object with ``encode(text)``, or the factory that takes a model name
    and returns one.

    A registered tokenizer can be either, as ``TokenCounter`` accepts both. The object must count a
    text (a sequence that is not empty), accept
    the empty text (the estimate counts it as one token) and give the same answer twice.
    """
    built: list[Any] = []

    def resolve() -> None:
        encoder = tokenizer if callable(getattr(tokenizer, "encode", None)) else tokenizer(model)
        require(callable(getattr(encoder, "encode", None)), "the tokenizer has no encode(text)")
        built.append(encoder)

    def encodes() -> None:
        require(len(built[0].encode("hello world")) > 0, "encode must return tokens for a text")

    def empty() -> None:
        require(len(built[0].encode("")) >= 0, "encode of an empty text must return a sequence")

    def repeatable() -> None:
        require(
            list(built[0].encode("hello world")) == list(built[0].encode("hello world")),
            "encode must give the same tokens for the same text",
        )

    checks: list[Check] = [
        ("resolves", resolve),
        ("encodes", encodes),
        ("empty", empty),
        ("repeatable", repeatable),
    ]
    return await run_checks("tokenizer", tokenizer, checks)


__all__ = ["check_provider", "check_tokenizer"]
