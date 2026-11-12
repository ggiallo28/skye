"""A forced capability choice, emulated for the models that refuse one (decision D109).

``capability_choice="required"`` or a capability name forces the model to call a capability. Some
models refuse the forced form with a 400 (Claude Opus 5.5, Sonnet 5.5, Fable 5.1, Mythos 5.1: the
adapter says which through ``refuses_forced_choice``). For them the client sends the request with
``capability_choice="auto"`` and one instruction appended at the end of the conversation, checks
that the answer holds the call, tries once more if it does not, and then raises
:class:`~skye.base.exceptions.CapabilityChoiceError`.

The conversation stays append-only, as those models require (preserved thinking: a reasoning block
is tied to the system prompt, the tool list and every earlier message):

- nothing already in the conversation is edited; the instruction is a new message at the end, and
  the response returns it in ``added_messages`` so the caller keeps it in its history;
- the tool list stays the same unless the request sets ``force_choice=True``, which sends only the
  named capability and is allowed only before the model's first answer (no ``AssistantMessage``
  yet), when there is no earlier reasoning to invalidate.

Streaming sends the emulated request once, with no check and no retry.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from skye.base.completion import CompleteRequest, CompleteResponse
from skye.base.exceptions import CapabilityChoiceError, ValidationError

#: The attempts of an emulated choice: the first and one retry.
ATTEMPTS = 2


def forced_choice(request: CompleteRequest) -> str | None:
    """``"required"`` or the capability name the request forces, or ``None`` when it forces none."""
    choice = request.capability_choice
    if not choice or choice == "auto" or not request.capabilities:
        return None
    return choice


def capability_name(capability: Any) -> str:
    """The name of one offered capability: a ``CapabilityInterface`` or a dict of a provider."""
    if isinstance(capability, dict):
        if "function" in capability:
            return str(capability["function"].get("name", ""))
        if "toolSpec" in capability:
            return str(capability["toolSpec"].get("name", ""))
        return str(capability.get("name", ""))
    return str(capability.get_schema().name)


def instruction(choice: str) -> str:
    """The sentence that asks the model for the call it cannot be forced to make."""
    if choice == "required":
        return "Answer now with a call to one of the capabilities offered, and nothing else."
    return f"Answer now with a call to the capability `{choice}`, and nothing else."


def emulated_request(request: CompleteRequest) -> tuple[CompleteRequest, list[Any]]:
    """The request to send instead of the forced one, and the messages it adds.

    Raises:
        ValidationError: If ``force_choice`` is set after the model's first answer, or the forced
            name is not among the capabilities offered.
    """
    from skye.base.messages import AssistantMessage, UserMessage

    choice = forced_choice(request)
    if choice is None:
        return request, []
    capabilities = list(request.capabilities or [])
    if choice != "required":
        names = [capability_name(c) for c in capabilities]
        if choice not in names:
            raise ValidationError(
                f"capability_choice names '{choice}', which is not among the capabilities offered: "
                f"{', '.join(names)}",
                field="capability_choice",
                value=choice,
            )
    messages = list(request.messages or [])
    if request.force_choice and choice != "required":
        if any(isinstance(m, AssistantMessage) for m in messages):
            raise ValidationError(
                "force_choice=True sends only the chosen capability, which changes the tool list; "
                "this model ties its earlier reasoning to the tool list, so the change is allowed "
                "only before its first answer. Leave force_choice False to keep every capability "
                "and ask for the call in an instruction.",
                field="force_choice",
                value=True,
            )
        capabilities = [c for c in capabilities if capability_name(c) == choice]
    added = [UserMessage(content=instruction(choice))]
    changed = dataclasses.replace(
        request,
        messages=[*messages, *added],
        capabilities=capabilities,
        capability_choice="auto",
    )
    return changed, added


def satisfied(choice: str, response: CompleteResponse) -> bool:
    """Whether the answer holds the call the request asked for."""
    calls = response.capability_calls or []
    if choice == "required":
        return bool(calls)
    return any(call.name == choice for call in calls)


def complete_emulated(
    request: CompleteRequest,
    send: Callable[[CompleteRequest], CompleteResponse],
    provider: str,
) -> CompleteResponse:
    """Send the emulated request, check the answer, retry once, then raise.

    Args:
        request: The request as the caller wrote it (with the forced choice).
        send: One completion with the transport's own retries (``_complete_with_retry``).
        provider: The provider label, for the error.

    Raises:
        CapabilityChoiceError: If no attempt calls the capability asked for.
    """
    choice = forced_choice(request)
    assert choice is not None
    changed, added = emulated_request(request)
    response: CompleteResponse | None = None
    for _ in range(ATTEMPTS):
        response = send(changed)
        if satisfied(choice, response):
            response.added_messages = list(added)
            response.metadata = {**response.metadata, "capability_choice_emulated": True}
            return response
    raise CapabilityChoiceError(
        f"The model {request.model} answered without calling "
        f"{'a capability' if choice == 'required' else repr(choice)} after {ATTEMPTS} attempts "
        "(it refuses a forced choice, so Skye asked for the call in an instruction)",
        provider=provider,
        capability_choice=choice,
        attempts=ATTEMPTS,
        last_content=response.content if response is not None else None,
    )
