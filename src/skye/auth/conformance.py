# Requirement 58.4, D98, D111
"""``check_credential_source``: the conformance function of the kind ``auth`` owns.

It runs offline, returns the names of the checks it passed and raises an ``AssertionError`` that
names the first that fails
(``skye.store.check_backend`` is the model). It is a coroutine function, so one runner awaits every
kind alike.

Example:
    >>> import asyncio
    >>> from skye.auth.conformance import check_credential_source
    >>> class Token:
    ...     def apply(self, method, url, headers, body=b""):
    ...         return {**headers, "Authorization": "Bearer x"}
    >>> asyncio.run(check_credential_source(Token))
    ['builds', 'shape', 'apply']

Raises: ``AssertionError`` naming the first failed check.
Missing: a secret source (it has ``get`` and no ``apply``) is checked by its shape; ``apply`` is
called only on an authenticator.
Concurrency: nothing is shared; each call builds its own object.
"""

from __future__ import annotations

from typing import Any

from skye.base.conformance import Check, require, run_checks


async def check_credential_source(factory: Any, **config: Any) -> list[str]:
    """Check a credential source: ``factory(**config)`` builds an authenticator (``apply``) or a
    secret source (``get``).

    An authenticator must return a new dict of headers, leave the headers it was given as they were,
    and keep them in the answer.
    """
    built: list[Any] = []
    headers = {"Accept": "application/json"}

    def shape() -> None:
        source = built[0]
        require(
            callable(getattr(source, "apply", None)) or callable(getattr(source, "get", None)),
            "a source has apply(method, url, headers, body) or get(name)",
        )

    def apply() -> None:
        source = built[0]
        if not callable(getattr(source, "apply", None)):
            return
        sent = dict(headers)
        signed = source.apply("GET", "https://example.invalid/path", sent, b"")
        require(isinstance(signed, dict), "apply must return a dict of headers")
        require(sent == headers, "apply must not change the headers it was given")
        require(signed is not sent, "apply must return a new dict")
        require(
            all(signed.get(key) == value for key, value in headers.items()),
            "apply must keep the headers it was given",
        )

    checks: list[Check] = [
        ("builds", lambda: built.append(factory(**config))),
        ("shape", shape),
        ("apply", apply),
    ]
    return await run_checks("credential source", factory, checks)


__all__ = ["check_credential_source"]
