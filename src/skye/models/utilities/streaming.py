"""Stdlib Server-Sent Events (``text/event-stream``) parser.

Implements the WHATWG SSE line protocol: ``field: value`` lines, blank line
dispatches an event, ``:`` lines are comments, multiple ``data`` lines are
joined with ``\\n``. Input is any iterable of lines (``str`` or ``bytes``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SSEEvent:
    """A single dispatched server-sent event."""

    data: str
    event: str = "message"
    id: str | None = None
    retry: int | None = None


def parse_sse(lines: Iterable[str | bytes]) -> Iterator[SSEEvent]:
    """Yield :class:`SSEEvent` objects from an iterable of raw SSE lines."""
    data: list[str] = []
    event = "message"
    last_id: str | None = None
    retry: int | None = None
    has_fields = False

    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")

        if line == "":
            if has_fields and data:
                yield SSEEvent("\n".join(data), event, last_id, retry)
            data, event, retry, has_fields = [], "message", None, False
            continue
        if line.startswith(":"):
            continue

        name, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]

        if name == "data":
            data.append(value)
            has_fields = True
        elif name == "event":
            event = value or "message"
            has_fields = True
        elif name == "id":
            if "\0" not in value:
                last_id = value
        elif name == "retry":
            if value.isdigit():
                retry = int(value)

    if has_fields and data:  # stream ended without trailing blank line
        yield SSEEvent("\n".join(data), event, last_id, retry)
