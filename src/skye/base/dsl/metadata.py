# decision D62
"""Front matter of a ``.skye`` file: metadata between two ``---`` lines at the top, written in TOML.

```text
---
title = "Support router"
version = "1.2"
tags = ["support", "prod"]
---
router "support" { ... }
```

The content is TOML (``key = value``, read with the standard library's ``tomllib``), the same
``key = value`` form as the attributes of a block. YAML is not read: a ``key: value``
line is reported with the fix. The front matter is replaced by empty lines before the text is
tokenized, so every line number of the rest of the file stays the same.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

from skye.base.dsl.errors import Diagnostic

#: The line that opens and closes the front matter.
FENCE = "---"

_YAML_LINE = re.compile(r"^\s*[A-Za-z_][\w.-]*\s*:(\s|$)")
_TOML_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")


def split_metadata(text: str, filename: str) -> tuple[dict[str, Any], str, list[Diagnostic]]:
    """Separate the front matter from the rest of a ``.skye`` text.

    Args:
        text: The whole text of the file.
        filename: The name used in diagnostics.

    Returns:
        The metadata (an empty dict when there is no front matter), the text with the front matter
        replaced by as many empty lines, and the mistakes found in the front matter.
    """
    lines = text.split("\n")
    first = lines[0].lstrip("\ufeff").rstrip("\r ")
    if first != FENCE:
        return {}, text, []
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r ") == FENCE), None)
    if close is None:
        problem = Diagnostic(
            file=filename,
            line=1,
            column=1,
            reason='the front matter opened by "---" is never closed',
            fix='Add a line with "---" after the metadata.',
        )
        return {}, text, [problem]
    body = "\n" * (close + 1) + "\n".join(lines[close + 1 :])
    content = lines[1:close]
    errors: list[Diagnostic] = []
    for offset, text_line in enumerate(content):
        if _YAML_LINE.match(text_line) and "=" not in text_line:
            key = text_line.split(":", 1)[0].strip()
            errors.append(
                Diagnostic(
                    file=filename,
                    line=offset + 2,
                    column=1,
                    reason="front matter is TOML, not YAML",
                    fix=f"Write {key} = <value> (strings in quotes).",
                )
            )
    if errors:
        return {}, body, errors
    try:
        metadata = tomllib.loads("\n".join(content))
    except tomllib.TOMLDecodeError as exc:
        match = _TOML_POSITION.search(str(exc))
        if match:
            line, column = int(match.group(1)) + 1, int(match.group(2))
        else:  # "at end of document": the mistake is on the last line of the front matter
            line, column = max(close, 2), 1
        reason = _TOML_POSITION.sub("", str(exc)).strip()
        errors.append(
            Diagnostic(
                file=filename,
                line=line,
                column=column,
                reason=f"front matter: {reason}",
                fix='Write key = value; strings in quotes, lists as ["a", "b"].',
            )
        )
        return {}, body, errors
    return metadata, body, []


def format_metadata(metadata: dict[str, Any]) -> str:
    """The front matter text (with both ``---`` lines) for ``metadata``; empty without metadata.

    Values may be strings, numbers, booleans, lists of those and nested tables (dicts).
    """
    if not metadata:
        return ""
    plain = {k: v for k, v in metadata.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in metadata.items() if isinstance(v, dict)}
    out = [FENCE, *(f"{_key(k)} = {_value(v)}" for k, v in plain.items())]
    for name, table in tables.items():
        out.append(f"[{_key(name)}]")
        out.extend(f"{_key(k)} = {_value(v)}" for k, v in table.items())
    out.append(FENCE)
    return "\n".join(out) + "\n"


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _value(key)


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'
