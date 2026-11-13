"""The formatter of the ``.skye`` language (``skye fmt``): one layout, comments kept.

It works on the text, not on the block models, so nothing written by hand is lost: comments,
``\"\"\"`` strings and the front matter stay as they are. What it changes:

* indentation: two spaces for each line that opens a ``{``, ``[`` or ``(`` still open (a line
  that opens two, ``list({``, adds one level, not two); a line that starts with a closing bracket
  goes back to the level of the line that opened it. The lines inside a ``/* */`` comment move
  with its first line; the lines inside a ``\"\"\"`` string are never touched (their text is
  the value);
* trailing spaces and tabs are removed (outside ``\"\"\"`` strings);
* blank lines: never more than one in a row, none at the start of the file, exactly one after the
  front matter, and the file ends with one newline.

:func:`format_text` refuses a text that does not build, and checks that the formatted text builds
the same blocks and metadata (it never changes what a file means). Formatting twice gives the same
text.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from skye.base.dsl.errors import Diagnostic
from skye.base.dsl.metadata import FENCE
from skye.base.dsl.parser import parse_collect

INDENT = "  "
_OPEN = "{[("
_CLOSE = "}])"


class FormatError(ValueError):
    """The text cannot be formatted: it has mistakes, or formatting would change its meaning."""

    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []


@dataclass
class _Line:
    text: str
    depth: int = 0  # the indent level of the line (inside the brackets open at its start)
    close_depth: int = 0  # the indent level when the line starts with a closing bracket
    verbatim: bool = False  # inside a \"\"\" string: written back unchanged
    comment_tail: bool = False  # inside a /* */ comment that started on an earlier line


def _scan(lines: list[str]) -> list[_Line]:
    """Bracket depth and string / comment state at the start of every line."""
    out: list[_Line] = []
    opened: list[int] = []  # for each open bracket, the indent level of the line that opened it
    in_triple = False
    in_comment = False
    for raw in lines:
        depth = opened[-1] + 1 if opened else 0
        close_depth = opened[-1] if opened else 0
        out.append(_Line(raw, depth, close_depth, verbatim=in_triple, comment_tail=in_comment))
        stripped = raw.strip()
        level = close_depth if stripped and stripped[0] in _CLOSE else depth
        i, n = 0, len(raw)
        while i < n:
            if in_triple:
                close = raw.find('"""', i)
                while close > 0 and raw[close - 1] == "\\":
                    close = raw.find('"""', close + 1)
                if close == -1:
                    break
                in_triple, i = False, close + 3
                continue
            if in_comment:
                close = raw.find("*/", i)
                if close == -1:
                    break
                in_comment, i = False, close + 2
                continue
            ch = raw[i]
            if raw.startswith('"""', i):
                in_triple, i = True, i + 3
            elif ch == '"':
                i += 1
                while i < n and raw[i] != '"':
                    i += 2 if raw[i] == "\\" else 1
                i += 1
            elif ch == "#":
                break
            elif raw.startswith("/*", i):
                in_comment, i = True, i + 2
            else:
                if ch in _OPEN:
                    opened.append(level)
                elif ch in _CLOSE and opened:
                    opened.pop()
                i += 1
    return out


def _layout(body: str) -> list[str]:
    lines = body.split("\n")
    scanned = _scan(lines)
    out: list[str] = []
    shift = 0  # how far the first line of the current /* */ comment moved
    for line in scanned:
        if line.verbatim:
            out.append(line.text)
            continue
        if line.comment_tail:
            stripped = line.text.rstrip()
            if shift >= 0:
                out.append(" " * shift + stripped if stripped else "")
            else:
                cut = min(-shift, len(stripped) - len(stripped.lstrip(" ")))
                out.append(stripped[cut:])
            continue
        content = line.text.strip()
        if not content:
            out.append("")
            continue
        depth = line.close_depth if content[0] in _CLOSE else line.depth
        indent = INDENT * max(depth, 0)
        old_indent = len(line.text) - len(line.text.lstrip(" \t"))
        shift = len(indent) - old_indent
        out.append(indent + content)
    return out


def _squeeze(lines: list[str]) -> list[str]:
    """No blank line at the start, at most one in a row, none at the end."""
    out: list[str] = []
    for line in lines:
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return out


def _split_front(text: str) -> tuple[list[str], str]:
    """The front matter lines (both fences included, trailing spaces removed) and the rest."""
    lines = text.split("\n")
    if not lines or lines[0].lstrip("﻿").rstrip() != FENCE:
        return [], text
    for index in range(1, len(lines)):
        if lines[index].rstrip() == FENCE:
            front = [FENCE, *(line.rstrip() for line in lines[1:index]), FENCE]
            return front, "\n".join(lines[index + 1 :])
    return [], text  # an unclosed front matter is reported by the checker


_POSITION = {"line", "column", "source", "via"}


def _shape(node: Any) -> Any:
    """The syntax tree without positions and without the spacing of expressions, to compare two
    texts."""
    if isinstance(node, list | tuple):
        return [_shape(item) for item in node]
    if isinstance(node, dict):
        return {key: _shape(value) for key, value in node.items()}
    if is_dataclass(node) and not isinstance(node, type):
        return {
            f.name: (
                " ".join(getattr(node, f.name).split())
                if f.name == "text"
                else _shape(getattr(node, f.name))
            )
            for f in fields(node)
            if f.name not in _POSITION and not f.name.endswith(("_line", "_column"))
        }
    return node


def format_text(text: str, filename: str | None = None) -> str:
    """The text of a ``.skye`` file in the standard layout.

    Args:
        text: The ``.skye`` text.
        filename: The name used in the diagnostics of :class:`FormatError`.

    Returns:
        The formatted text (equal to ``text`` when it is already formatted).

    Raises:
        FormatError: If the text has mistakes (``diagnostics`` lists them), or if the formatted text
            would build differently (a bug of the formatter; the text is left alone).
    """
    from skye.base.dsl.build import build
    from skye.base.dsl.emit import to_text

    tree, problems = parse_collect(text, filename)
    # A file with an include, and a partial, are compared as written (no partial is read): the same
    # tree before and after.
    included = not problems and (tree.has_include or tree.metadata.get("partial") is True)
    before = None if included else build(text, filename=filename)
    found = problems or (before.diagnostics if before else [])
    if found:
        raise FormatError("the file has mistakes; fix them first", found)
    text = text.replace("\r\n", "\n")
    front, body = _split_front(text)
    lines = _squeeze(_layout(body.expandtabs(len(INDENT))))
    result = "\n".join(front + ([""] if front and lines else []) + lines) + "\n"
    if before is None:
        again, problems = parse_collect(result, filename)
        same = not problems and _shape(again) == _shape(tree)
        diagnostics = problems
    else:
        after = build(result, filename=filename)
        # Compared through to_text: the models also carry line and column numbers, which move.
        same = not after.diagnostics and to_text(after) == to_text(before)
        diagnostics = after.diagnostics
    if not same:
        raise FormatError(
            "formatting would change what the file means; it was left as it is", diagnostics
        )
    return result


__all__ = ["FormatError", "format_text"]
