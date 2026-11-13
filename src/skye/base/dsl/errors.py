# Requirement 54.3
"""Diagnostics of the ``.skye`` language: where a mistake is, what it is and how to fix it.

The parser and the validators do not stop at the first mistake: they collect every
:class:`Diagnostic` they can find and report them together, in one :class:`SkyeSyntaxError`.
"""

from __future__ import annotations

import difflib
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from skye.base.exceptions import SkyeError

#: The file name used in a message when the text did not come from a file.
DEFAULT_FILENAME = "<string>"

#: The deepest nesting a file may have: blocks, maps, lists and brackets of an expression. At
#: Python's default recursion limit the parser, the checker and the emitter survive about 490
#: levels, so 100 leaves a wide margin (also for the frames of the caller).
MAX_DEPTH = 100

#: The fix given with a nesting diagnostic.
TOO_DEEP_FIX = "Move the inner part into its own flow or prompt."


def too_deep_reason() -> str:
    """The reason of the diagnostic for a file nested more than :data:`MAX_DEPTH` levels."""
    return f"nesting is too deep (more than {MAX_DEPTH} levels)"


@dataclass(frozen=True, kw_only=True)
class Diagnostic:
    """One mistake found in a ``.skye`` text.

    Attributes:
        file: The file name (``<string>`` when the text did not come from a file).
        line: The line, counted from 1.
        column: The column, counted from 1.
        reason: What is wrong.
        fix: What to do about it (an ``Add: ...`` line or a ``Did you mean ...?`` suggestion), or
            an empty string.
        via: When the mistake is in a file that an ``include`` brought, the use sites that
            brought it, as ``(file, line, column)``; empty otherwise.
    """

    file: str
    line: int
    column: int
    reason: str
    fix: str = ""
    via: tuple[tuple[str, int, int], ...] = ()

    @property
    def message(self) -> str:
        """The reason followed by the fix, as one sentence."""
        return f"{self.reason} {self.fix}" if self.fix else self.reason

    def format(self) -> str:
        """The diagnostic as ``file:line:col message``, written to be pasted back to a model."""
        used = "".join(f" (used from {f}:{n}:{c})" for f, n, c in self.via)
        return f"{self.file}:{self.line}:{self.column} {self.message}{used}"


class SkyeSyntaxError(SkyeError):
    """One or more mistakes in a ``.skye`` text.

    Args:
        diagnostics: Every mistake found (one is enough).

    Attributes:
        diagnostics: The mistakes, in the order of the file.
        file: The file name of the first mistake.
        line: The line of the first mistake.
        column: The column of the first mistake.
        reason: The reason of the first mistake.
        fix: The fix of the first mistake (may be empty).
    """

    def __init__(self, diagnostics: Iterable[Diagnostic] | Diagnostic) -> None:
        items = [diagnostics] if isinstance(diagnostics, Diagnostic) else list(diagnostics)
        if not items:
            raise ValueError("SkyeSyntaxError needs at least one diagnostic")
        self.diagnostics: list[Diagnostic] = items
        first = items[0]
        self.file = first.file
        self.line = first.line
        self.column = first.column
        self.reason = first.reason
        self.fix = first.fix
        super().__init__(
            "\n".join(item.format() for item in items),
            {"errors": [(item.line, item.column, item.message) for item in items]},
        )

    def __str__(self) -> str:
        """Every diagnostic, one per line."""
        return self.message


def suggest(name: str, candidates: Collection[str]) -> str | None:
    """The candidate closest to ``name`` (a typo), or ``None`` when none is close enough.

    Args:
        name: The word that was written.
        candidates: The words that exist.
    """
    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    if not matches:
        lowered = {c.lower(): c for c in candidates}
        return lowered.get(name.lower())
    return matches[0]


def did_you_mean(name: str, candidates: Collection[str]) -> str:
    """``Did you mean "x"?`` for a typo of ``name``, or an empty string."""
    match = suggest(name, candidates)
    return f'Did you mean "{match}"?' if match else ""
