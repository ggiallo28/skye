"""The syntax tree of a ``.skye`` file: every node knows its line and column.

The tree is neutral: it says what was written, not what it means. The block models
(:mod:`skye.base.dsl.specs`) are built from it by :mod:`skye.base.dsl.build`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(kw_only=True)
class Node:
    """A node with its position (line and column count from 1).

    A node that an ``include`` brought from another file also says where it comes from:
    ``source`` is the name of that file (empty for a node of the file itself) and ``via`` the
    chain of sites that used it, each as ``(file, line, column)``.
    """

    line: int
    column: int
    source: str = ""
    via: tuple[tuple[str, int, int], ...] = ()


@dataclass(kw_only=True)
class Str(Node):
    """A string (``"text"`` or ``\"\"\"multi-line text\"\"\"``); ``value`` is the decoded text."""

    value: str
    raw: str = ""


@dataclass(kw_only=True)
class Num(Node):
    """A number."""

    value: int | float
    raw: str = ""


@dataclass(kw_only=True)
class Bool(Node):
    """``true`` or ``false``."""

    value: bool


@dataclass(kw_only=True)
class Name(Node):
    """A bare or dotted name: a reference (``registry.x``, ``step.A.output``) or a keyword
    (``end``).

    Whether the name is valid is decided by the checker, not by the parser.
    """

    path: tuple[str, ...]

    @property
    def text(self) -> str:
        """The name as written, with dots."""
        return ".".join(self.path)


@dataclass(kw_only=True)
class Expr(Node):
    """An expression, kept as the text of the file (it is checked with ``ast``, never evaluated
    here).
    """

    text: str


@dataclass(kw_only=True)
class TypeCall(Node):
    """A typed declaration such as ``string("x")`` or ``number(0)`` (``default`` is ``None`` if
    absent).

    ``list({ a = string }, [])`` and ``map({ a = string }, {})`` have a second argument,
    ``second``: ``default`` holds the shape and ``second`` the default value.
    """

    name: str
    default: Value | None = None
    second: Value | None = None


@dataclass(kw_only=True)
class ListNode(Node):
    """A list ``[ a, b ]``."""

    items: list[Value] = field(default_factory=list)


@dataclass(kw_only=True)
class MapEntry(Node):
    """One ``key = value`` entry of a map (the position is the one of the key).

    Inside an ``output`` block an entry may end with a string, its description
    (``amount = number "Amount of the line"``); elsewhere ``description`` is always ``None``.
    In the ``variables`` map of a prompt an entry may be ``use name``: then ``use`` is true,
    ``key`` is the name and ``value`` a :class:`Name`; or ``override name = ...``: then ``override``
    is true and the entry replaces the one that a ``use`` brought.
    """

    key: str
    value: Value
    description: Str | None = None
    use: bool = False
    override: bool = False


@dataclass(kw_only=True)
class MapNode(Node):
    """A map ``{ key = value, ... }``."""

    entries: list[MapEntry] = field(default_factory=list)


Value = Str | Num | Bool | Name | Expr | TypeCall | ListNode | MapNode


@dataclass(kw_only=True)
class Attribute(Node):
    """``name = value``; also ``set field = value`` and ``emit "event"`` (``keyword`` says which).

    Attributes:
        name: The attribute name (the field for ``set``, ``emit`` for ``emit``).
        value: The value.
        keyword: ``""`` for a plain attribute, ``set`` or ``emit``.
        name_line: The line of the name.
        name_column: The column of the name.
        description: The string after the value, only inside an ``output`` block
            (``total = number "Total amount"``); ``None`` elsewhere.
    """

    name: str
    value: Value
    keyword: str = ""
    name_line: int = 0
    name_column: int = 0
    description: Str | None = None


@dataclass(kw_only=True)
class Block(Node):
    """``KIND ["label"] { body }``.

    Attributes:
        kind: The first word (``router``, ``flow``, ``step``, ``when``, ``else``, ``each`` ...).
        label: The label (a string or a dotted name), or ``None``.
        value: The value of the shorthand ``route "x" = [...]``, or ``None``.
        head: The condition of ``when`` or the list of ``each``, or ``None``.
        var: The loop variable of ``each``.
        body: The attributes and blocks inside the braces, in order.
        braces: ``False`` for a block written with no braces (``placeholder "history"``).
        override: True for ``override when ...``, which replaces the block that a ``use`` brought.
    """

    kind: str
    label: Str | Name | None = None
    value: Value | None = None
    head: Value | None = None
    var: str = ""
    body: list[Attribute | Block] = field(default_factory=list)
    braces: bool = True
    override: bool = False

    @property
    def label_text(self) -> str | None:
        """The label as text, or ``None``."""
        if isinstance(self.label, Str):
            return self.label.value
        if isinstance(self.label, Name):
            return self.label.text
        return None

    def attributes(self) -> list[Attribute]:
        """The attributes of the body."""
        return [item for item in self.body if isinstance(item, Attribute)]

    def blocks(self) -> list[Block]:
        """The blocks of the body."""
        return [item for item in self.body if isinstance(item, Block)]


@dataclass(kw_only=True)
class Tree:
    """A parsed file.

    Attributes:
        filename: The file name used in diagnostics.
        blocks: The top-level blocks, in order.
        metadata: The front matter (``---`` ... ``---`` at the top, TOML); empty without one.
        has_include: True when the file holds an ``include``, a ``from ... import`` or a ``use``.
    """

    filename: str
    blocks: list[Block] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    has_include: bool = False
