# Requirement 63, D116
"""The ``include`` of the ``.skye`` language: partial files, ``from ... import`` and ``use``.

A partial is a file shaped like a prompt (``partial = true`` in its front matter, one ``prompt``
block with its ``variables`` and its messages). A file takes one by ``include "path" as name`` (the
whole file) or ``from "path" import a, b as c`` (names one by one), and writes ``use name`` exactly
where the content goes. The place gives the kind: in ``variables`` ``use`` brings entries, in a
message or prompt body it brings items.

:func:`expand` runs before the checks: it replaces every ``use`` by a copy of what it brings, so the
rest of the language sees a file written without ``include``. ``base`` reads no file: the text of
a partial comes from a *resolver* given by the caller.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Any

from skye.base.dsl.errors import Diagnostic, did_you_mean
from skye.base.dsl.parser import parse_collect
from skye.base.dsl.tree import Attribute, Block, MapEntry, MapNode, Name, Node, Str, Tree

#: The most ``include`` and ``from`` lines one document may hold.
MAX_INCLUDES = 64
#: The most text, in characters, that the partials of one document may bring.
MAX_INCLUDED_CHARS = 1_048_576

#: The fix of a statement written outside a prompt.
PROMPTS_ONLY = "Write it in a file that has a prompt."

#: Why a partial cannot be built alone (``check_text`` leaves it out: it is checked where used).
PARTIAL_ALONE = "this file is a partial (partial = true) and cannot be built alone"

# : A line that reads a file (``include "x"`` or ``from "x" import``): a text with one depends on
# files that the text does not hold.
INCLUDE_LINE = re.compile(r'^\s*(?:include|from)\s+"', re.MULTILINE)
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")  # a scheme (``https:``) or a drive (``C:``)


@dataclass(frozen=True, kw_only=True)
class Resolved:
    """What a resolver returns for a target.

    Attributes:
        text: The text of the file.
        name: The name shown in diagnostics (a path relative to the root, a member of an archive).
        key: The identity of the file (a real path, or the member name): two targets that reach the
            same file give the same key.
    """

    text: str
    name: str
    key: str


#: ``resolver(target, from_key) -> Resolved``; it raises ``FileNotFoundError``, ``KeyError`` or
#: ``ValueError`` (a target outside the root). ``from_key`` is the key of the including file.
Resolver = Callable[[str, "str | None"], Resolved]


@dataclass(kw_only=True)
class _Partial:
    name: str
    prompt: Block
    entries: list[MapEntry]
    size: int
    line: int  # the line of the include in the including file


def _copy(node: Any, source: str, via: tuple[tuple[str, int, int], ...]) -> Any:
    """A copy of a node and of everything under it, marked as brought from ``source``."""
    if isinstance(node, list):
        return [_copy(item, source, via) for item in node]
    if is_dataclass(node) and not isinstance(node, type):
        changes = {f.name: _copy(getattr(node, f.name), source, via) for f in fields(node)}
        if isinstance(node, Node):
            changes.update(source=source, via=via)
        return type(node)(**changes)
    return node


def _where(node: Node, file: str) -> str:
    return f"{node.source or file}:{node.line}:{node.column}"


def _cond(head: Any) -> str:
    """The condition of a ``when`` as text: ``name`` or ``not name``."""
    return head.text if isinstance(head, Name) else " ".join(getattr(head, "text", "").split())


def _tests_name(head: Any, name: str) -> bool:
    """True when a ``when`` condition is only ``name`` or ``not name``."""
    if isinstance(head, Name):
        return head.path == (name,)
    text = getattr(head, "text", None)
    return text is not None and " ".join(text.split()) == f"not {name}"


def _no_use(
    entry: MapEntry, entries: list[MapEntry], brought: dict[str, int], replaced: dict[str, int]
) -> tuple[str, str]:
    """The reason and the fix of an ``override`` that replaces nothing."""
    name = entry.key
    reason = f'cannot override "{name}": '
    if name in replaced:
        return reason + f"it is already overridden at line {replaced[name]}", "Keep one override."
    reason += f"no use before this line brought it; brought: {', '.join(brought) or 'none'}"
    later = next((e.line for e in entries if e.use and e.key == name and e.line > entry.line), None)
    if later is not None:
        return reason, f'The use of "{name}" is at line {later}; write the override after it.'
    return reason, "Write the use before the override."


def _first_override(items: list[Any]) -> Block | None:
    """The first ``override when`` block of a tree, searched in the bodies."""
    for item in items:
        if isinstance(item, Block):
            if item.override:
                return item
            if (found := _first_override(item.body)) is not None:
                return found
    return None


class _Expander:
    def __init__(self, tree: Tree, resolver: Resolver | None, key: str | None) -> None:
        self.tree = tree
        self.file = tree.filename
        self.key = key or tree.filename
        self.resolver = resolver
        self.errors: list[Diagnostic] = []
        self.loaded: dict[str, _Partial] = {}
        self.aliases: dict[str, _Partial] = {}
        self.names: dict[str, tuple[_Partial, str]] = {}
        self.declared: dict[str, int] = {}  # the alias or local name -> the line that made it
        self.chars = 0

    def error(self, node: Node, reason: str, fix: str = "") -> None:
        self.errors.append(
            Diagnostic(
                file=node.source or self.file,
                line=node.line,
                column=node.column,
                reason=reason,
                fix=fix,
                via=node.via,
            )
        )

    # -- the include and from lines ------------------------------------------------------------
    def run(self) -> tuple[Tree, list[Diagnostic]]:
        lines = [b for b in self.tree.blocks if b.kind in ("include", "from")]
        kinds = {b.kind for b in self.tree.blocks}
        if "prompt" not in kinds and kinds & {"router", "flow"}:
            first = lines[0] if lines else _first_override(self.tree.blocks)
            if first is not None:
                word = "override" if first.override else first.kind
                self.error(first, f"{word} is available in prompts only.", PROMPTS_ONLY)
            lines = []
        for number, line in enumerate(lines, 1):
            if number > MAX_INCLUDES:
                self.error(line, f"too many includes (more than {MAX_INCLUDES} in one document)")
                break
            self.statement(line)
        blocks = [b for b in self.tree.blocks if b.kind not in ("include", "from")]
        if not self.errors:
            blocks = [self.prompt(b) if b.kind == "prompt" else b for b in blocks]
        return replace(self.tree, blocks=blocks), self.errors

    def statement(self, line: Block) -> None:
        assert isinstance(line.label, Str)
        target = line.label.value
        if line.kind == "include" and not line.var:
            self.error(
                line,
                "an include needs a name",
                f'Write: include "{target}" as <name>',
            )
            return
        partial = self.load(line, target)
        if partial is None:
            return
        if line.kind == "include":
            self.declare(line, line.var, partial)
            return
        for item in (i for i in line.body if isinstance(i, Block)):
            original = item.label_text or ""
            local = item.var or original
            if original not in {e.key for e in partial.entries}:
                names = ", ".join(e.key for e in partial.entries) or "none"
                self.error(
                    item,
                    f'"{target}" has no variable "{original}"; it has: {names}',
                    did_you_mean(original, [e.key for e in partial.entries]),
                )
                continue
            self.declare(item, local, partial, original)

    def declare(
        self, node: Block, local: str, partial: _Partial, original: str | None = None
    ) -> bool:
        if local in self.declared:
            line = self.declared[local]
            if original is None:
                self.error(node, f'the alias "{local}" is already used at line {line}')
            else:
                self.error(
                    node,
                    f'"{local}" is already imported at line {line}',
                    f"Write: import {original} as other_{local}",
                )
            return False
        self.declared[local] = node.line
        if original is None:
            self.aliases[local] = partial
        else:
            self.names[local] = (partial, original)
        return True

    def load(self, line: Block, target: str) -> _Partial | None:
        if not target or target.startswith(("/", "\\")) or _URL.match(target):
            self.error(
                line.label or line,
                f'"{target}" is not a relative path',
                "An include takes a path relative to the file, such as lib/memory.skye.",
            )
            return None
        if self.resolver is None:
            self.error(
                line,
                f'cannot read "{target}": no resolver was given',
                "Pass resolver= to build, or load the file with skye.load.",
            )
            return None
        try:
            found = self.resolver(target, self.key)
        except (OSError, KeyError, ValueError) as exc:
            detail = exc.args[0] if exc.args else exc
            self.error(line, f'cannot read "{target}": {detail}')
            return None
        if found.key == self.key:
            self.error(line, f"include cycle: {self.file} -> {found.name}")
            return None
        if found.key in self.loaded:
            self.error(
                line, f'"{target}" is already included at line {self.loaded[found.key].line}'
            )
            return None
        self.chars += len(found.text)
        if self.chars > MAX_INCLUDED_CHARS:
            self.error(line, "the included files are too large (more than 1 MB of text)")
            return None
        partial = self.read(line, found)
        if partial is not None:
            self.loaded[found.key] = partial
        return partial

    def read(self, line: Block, found: Resolved) -> _Partial | None:
        tree, problems = parse_collect(found.text, found.name)
        if problems:
            self.errors.extend(problems)
            return None
        if tree.metadata.get("partial") is not True:
            self.error(
                line, f'"{found.name}" is not a partial', "Add partial = true to its front matter."
            )
            return None
        prompts = [b for b in tree.blocks if b.kind == "prompt"]
        if len(prompts) != 1 or len(tree.blocks) != 1 or tree.has_include:
            self.error(
                line,
                f'"{found.name}" is not a valid partial',
                "A partial holds one prompt block and no include, use or override.",
            )
            return None
        entries: list[MapEntry] = []
        for item in prompts[0].body:
            if isinstance(item, Attribute) and item.name == "variables":
                if isinstance(item.value, MapNode):
                    entries = item.value.entries
        return _Partial(
            name=found.name,
            prompt=prompts[0],
            entries=entries,
            size=len(found.text),
            line=line.line,
        )

    # -- the places of use ---------------------------------------------------------------------
    def prompt(self, block: Block) -> Block:
        return replace(block, body=self.items(block.body, None))

    def items(self, items: list[Any], message: Block | None) -> list[Any]:
        """The items of a body with every ``use`` replaced; ``message`` is the message the body
        belongs to (``None`` in the prompt body), which says where a whole file takes its items.
        """
        out: list[Any] = []
        used: dict[str, int] = {}
        for item in items:
            if isinstance(item, Attribute):
                if item.name == "variables" and isinstance(item.value, MapNode):
                    item = replace(item, value=self.variables(item.value))
                out.append(item)
            elif item.kind == "use":
                out.extend(self.use_items(item, used, message))
            elif item.override:
                self.override_block(item, out, message)
            else:
                inside = item if item.kind == "message" else message
                out.append(replace(item, body=self.items(item.body, inside)))
        return out

    # D117
    def override_block(self, item: Block, out: list[Any], message: Block | None) -> None:
        """Replace the block a ``use`` brought with the same condition."""
        cond = _cond(item.head)
        brought = [
            (i, _cond(b.head))
            for i, b in enumerate(out)
            if isinstance(b, Block) and b.kind == "when" and b.source
        ]
        for i, c in brought:
            if c == cond:
                out[i] = replace(item, body=self.items(item.body, message))
                return
        names = ", ".join(f"when {c}" for _, c in brought) or "none"
        self.error(
            item,
            f'cannot override "when {cond}": no use before this line brought it; brought: {names}',
            "Write the use before the override.",
        )

    def once(self, node: Node, name: str, used: dict[str, int]) -> bool:
        if name in used:
            self.error(node, f'"{name}" is already used at line {used[name]}')
            return False
        used[name] = node.line
        return True

    def lookup(self, node: Node, name: str) -> tuple[_Partial, str | None] | None:
        if name in self.aliases:
            return self.aliases[name], None
        if name in self.names:
            return self.names[name]
        known = ", ".join(sorted(self.declared)) or "none"
        self.error(
            node,
            f'"{name}" is not included or imported; the names here are: {known}',
            did_you_mean(name, list(self.declared)),
        )
        return None

    def sites(self, node: Node) -> tuple[tuple[str, int, int], ...]:
        return ((node.source or self.file, node.line, node.column),)

    def use_items(self, use: Block, used: dict[str, int], message: Block | None) -> list[Any]:
        name = use.label_text or ""
        if not isinstance(use.label, Name) or len(use.label.path) != 1:
            self.error(use, "use takes one name", "Write: use <name>")
            return []
        if not self.once(use, name, used):
            return []
        found = self.lookup(use, name)
        if found is None:
            return []
        partial, original = found
        container = self.container(use, partial, message)
        if container is None:
            return []
        self.chars += partial.size
        if self.chars > MAX_INCLUDED_CHARS:
            self.error(use, "the included files are too large (more than 1 MB of text)")
            return []
        if original is None:  # the whole file: every item of the container
            body = [
                i
                for i in container.body
                if not (isinstance(i, Attribute) and i.name == "variables")
            ]
        else:  # one name: its first-level ``when original`` and ``when not original`` blocks
            body = [
                i
                for i in container.body
                if isinstance(i, Block) and i.kind == "when" and _tests_name(i.head, original)
            ]
            if not body:
                self.error(
                    use,
                    f'"{partial.name}" has no text for "{original}"; it only has its entry',
                    f'Write the text in the file, or use "{original}" in variables.',
                )
        return _copy(body, partial.name, self.sites(use))  # type: ignore[no-any-return]

    def container(self, use: Block, partial: _Partial, message: Block | None) -> Block | None:
        """The block of the partial that a ``use`` takes its items from: its message of the same
        name when the ``use`` is in a message, else its prompt.
        """
        if message is None:
            return partial.prompt
        label = message.label_text
        for item in partial.prompt.body:
            if isinstance(item, Block) and item.kind == "message" and item.label_text == label:
                return item
        names = [
            i.label_text
            for i in partial.prompt.body
            if isinstance(i, Block) and i.kind == "message"
        ]
        self.error(
            use,
            f'"{partial.name}" has no message "{label}"',
            f"It has: {', '.join(str(n) for n in names) or 'none'}.",
        )
        return None

    def variables(self, node: MapNode) -> MapNode:
        entries: list[MapEntry] = []
        used: dict[str, int] = {}
        brought: dict[str, int] = {}  # a name a ``use`` brought -> its place in ``entries``
        replaced: dict[str, int] = {}  # a name already overridden -> the line of the override
        for entry in node.entries:
            if entry.override:
                if (at := brought.pop(entry.key, None)) is None:
                    self.error(entry, *_no_use(entry, node.entries, brought, replaced))
                else:
                    entries[at] = entry
                    replaced[entry.key] = entry.line
                continue
            if not entry.use:
                entries.append(entry)
                continue
            if not self.once(entry, entry.key, used):
                continue
            found = self.lookup(entry, entry.key)
            if found is None:
                continue
            partial, original = found
            taken = [e for e in partial.entries if original is None or e.key == original]
            if not taken:
                self.error(entry, f'"{partial.name}" has no variables')
                continue
            self.chars += partial.size
            for copy in _copy(taken, partial.name, self.sites(entry)):
                brought[copy.key] = len(entries)
                entries.append(copy)
        seen: dict[str, MapEntry] = {}
        for entry in entries:
            before = seen.setdefault(entry.key, entry)
            if before is not entry and (
                before.source or entry.source or before.override or entry.override
            ):
                self.error(
                    entry,
                    f'"{entry.key}" is defined twice: here and at {_where(before, self.file)}',
                    "Remove one, or do not use the part that has it.",
                )
        return replace(node, entries=entries)


def expand(
    tree: Tree, resolver: Resolver | None = None, key: str | None = None
) -> tuple[Tree, list[Diagnostic]]:
    """Replace every ``include``, ``from ... import`` and ``use`` of a tree by what it brings.

    Args:
        tree: The tree of the file (it is not changed).
        resolver: ``resolver(target, from_key) -> Resolved``; ``None`` when the caller has none.
        key: The identity of the file (to detect a file that includes itself); the file name by
            default.

    Returns:
        The tree with no ``include``, ``from`` or ``use``, and the mistakes found (the tree is only
        meant to be built when the list is empty).
    """
    return _Expander(tree, resolver, key).run()
