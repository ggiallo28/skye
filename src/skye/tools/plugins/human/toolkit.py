# Requirement 62.7, D111
"""``HumanToolkit``: the built-in toolkit ``human``, questions and escalations to a person.

A channel is an object with ``send(message) -> ticket`` and ``poll(ticket) -> reply or None``.
``file`` (needs
``directory``) writes ``<ticket>.json``; the person creates ``<ticket>.reply.txt``. ``console`` uses
stderr and a terminal.
It does not authenticate the person, send e-mail or chat, or suspend a run.

Example:
    >>> import tempfile
    >>> toolkit = HumanToolkit(channel="file", directory=tempfile.mkdtemp())
    >>> sent = toolkit.escalate.execute(reason="refund over the limit", summary="order 42")
    >>> sent.startswith("escalation sent, ticket ")
    True

Raises: ``ConfigurationError`` for an unknown channel; ``ValidationError`` for a bad option;
``CapabilityError`` from a tool
    for a bad text, severity or ticket, or an unanswered question (the error holds the ticket).
Missing: a text past 4000 characters is cut and says so.
Concurrency: no state outside the channel; the file channel writes atomically with ``os.replace``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from skye.base.exceptions import CapabilityError, ConfigurationError, ValidationError
from skye.tools.decorator import capability
from skye.tools.toolkit import Toolkit

SEVERITIES = ("low", "normal", "high", "urgent")
MAX_TEXT = 4000
_TICKET = re.compile(r"^[0-9a-f]{12}$")
_sleep = asyncio.sleep
_monotonic = time.monotonic


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ticket_ok(ticket: object) -> str:
    if not isinstance(ticket, str) or not _TICKET.match(ticket):
        raise CapabilityError("the ticket must be the 12 characters (0-9, a-f) returned")
    return ticket


@dataclass(frozen=True)
class EscalationMessage:
    """What a person receives."""

    kind: str
    text: str
    context: str = ""
    severity: str = "normal"
    created: str = ""


@runtime_checkable
class HumanChannel(Protocol):
    """The way a person is reached: ``send`` returns a ticket, ``poll`` the reply or ``None``."""

    def send(self, message: EscalationMessage) -> str: ...

    def poll(self, ticket: str) -> str | None: ...


class FileChannel:
    """A folder: ``<ticket>.json`` goes out, ``<ticket>.reply.txt`` comes back."""

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        if directory is None or str(directory) == "":
            raise ValidationError(
                "the channel 'file' needs the option directory", field="directory", value=None
            )
        self._dir = Path(directory)

    def send(self, message: EscalationMessage) -> str:
        ticket = uuid.uuid4().hex[:12]
        self._dir.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump({"ticket": ticket, **asdict(message)}, out, indent=2)
        os.replace(temporary, self._dir / f"{ticket}.json")
        return ticket

    def poll(self, ticket: str) -> str | None:
        reply = self._dir / f"{_ticket_ok(ticket)}.reply.txt"
        if not reply.is_file():
            return None
        return reply.read_text(encoding="utf-8").strip() or None


class ConsoleChannel:
    """Standard error and a terminal; it blocks, so not for a server."""

    def send(self, message: EscalationMessage) -> str:
        ticket = uuid.uuid4().hex[:12]
        print(f"[{message.kind} {ticket} {message.severity}] {message.text}", file=sys.stderr)
        if message.context:
            print(f"  context: {message.context}", file=sys.stderr)
        return ticket

    def poll(self, ticket: str) -> str | None:
        if not sys.stdin.isatty():
            return None
        return sys.stdin.readline().strip() or None


CHANNELS: dict[str, Any] = {"console": ConsoleChannel, "file": FileChannel}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"{name} must be a text that is not empty")
    return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + " [cut]"


class HumanToolkit(Toolkit):
    """Ask a person or escalate to one.

    Args:
        channel: ``"file"`` (default), ``"console"`` or an object with ``send`` and ``poll``.
        timeout: Seconds ``ask`` waits.
        poll_interval: Seconds between two looks for an answer.
        **channel_options: Options of the channel, such as ``directory``.
    """

    def __init__(
        self,
        *,
        channel: str | HumanChannel = "file",
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        **channel_options: Any,
    ) -> None:
        for option, value in (("timeout", timeout), ("poll_interval", poll_interval)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValidationError(
                    f"the option {option} of 'human' must be a positive number",
                    field=option,
                    value=value,
                )
        if isinstance(channel, str):
            if channel not in CHANNELS:
                raise ConfigurationError(
                    f"no channel named {channel!r}; the channels are {', '.join(sorted(CHANNELS))}",
                    {"channel": channel, "known": sorted(CHANNELS)},
                )
            built: HumanChannel = CHANNELS[channel](**channel_options)
            channel = built
        elif channel_options or not isinstance(channel, HumanChannel):
            raise ConfigurationError(
                "channel must be a name or an object with send and poll, and an object takes no "
                "options"
            )
        self._channel: HumanChannel = channel
        self._timeout = float(timeout)
        self._poll_interval = float(poll_interval)

    def _send(self, kind: str, text: str, context: str, severity: str) -> str:
        message = EscalationMessage(kind, text, context, severity, _now())
        return _ticket_ok(self._channel.send(message))

    @capability
    async def ask(self, question: str, context: str = "") -> str:
        """Ask a person and wait for the answer. Use it only when you cannot go on.

        Args:
            question: What to ask.
            context: What the person needs to answer.
        """
        ticket = self._send("question", _text(question, "question"), context[:MAX_TEXT], "normal")
        deadline = _monotonic() + self._timeout
        while True:
            reply = self._channel.poll(ticket)
            if reply is not None:
                return reply
            if _monotonic() >= deadline:
                raise CapabilityError(
                    f"the question was not answered in {self._timeout:g} seconds; "
                    f"check later with check_escalation, ticket {ticket}"
                )
            await _sleep(self._poll_interval)

    @capability
    def escalate(self, reason: str, summary: str, severity: str = "normal") -> str:
        """Hand a case to a person and go on. It does not wait; the result has a ticket.

        Args:
            reason: Why a person must look.
            summary: What happened so far.
            severity: low, normal, high or urgent.
        """
        if severity not in SEVERITIES:
            raise CapabilityError(f"severity must be one of {', '.join(SEVERITIES)}")
        ticket = self._send("escalation", _text(reason, "reason"), summary[:MAX_TEXT], severity)
        return f"escalation sent, ticket {ticket}"

    @capability
    def check_escalation(self, ticket: str) -> str:
        """Read the answer to a ticket, or say there is none yet.

        Args:
            ticket: The ticket given before.
        """
        reply = self._channel.poll(_ticket_ok(ticket))
        return reply if reply is not None else "no reply yet"
