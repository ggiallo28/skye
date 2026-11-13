# decision D55, Requirement 54.5
"""Expressions of the ``.skye`` language: a checker over ``ast`` and a small evaluator.

An expression is Python-compatible text, parsed with ``ast.parse(mode="eval")`` and checked
against a whitelist of nodes and of functions. It is never
passed to ``eval`` or ``exec``: :func:`evaluate` walks the checked tree itself.

Allowed: comparison, ``and``/``or``/``not``, ``+ - * / // %``, ``in``/``not in``, ``is``/``is not``,
names and attribute access (not names that start with ``_``), subscripts, constants, lists,
tuples, dicts, ``a if b else c`` and the functions ``len``, ``min``, ``max``, ``abs``,
``round``, ``str``, ``int``, ``float``.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from skye.base.dsl.errors import (
    DEFAULT_FILENAME,
    MAX_DEPTH,
    Diagnostic,
    too_deep_reason,
)
from skye.base.exceptions import SkyeError

#: The only functions an expression may call.
ALLOWED_FUNCTIONS: tuple[str, ...] = ("len", "min", "max", "abs", "round", "str", "int", "float")

_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "len": len,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "str": str,
    "int": int,
    "float": float,
}

_BIN: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
}
_CMP: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

#: The largest repeat count of ``"ab" * n`` or ``[0] * n`` (an expression must stay cheap).
_MAX_REPEAT = 10_000


@dataclass(frozen=True, kw_only=True)
class Expression:
    """An expression kept as text with its position in the file (a value in a block model).

    Attributes:
        text: The expression as written.
        line: The line where it starts.
        column: The column where it starts.
    """

    text: str
    line: int = 0
    column: int = 0


class SkyeExpressionError(SkyeError):
    """An expression could not be evaluated (a missing name, a bad operand, a division by zero)."""


def _chars(source: str, node: ast.AST) -> tuple[int, int]:
    """The (line offset, character column) of an ``ast`` node (``col_offset`` counts bytes)."""
    row = getattr(node, "lineno", 1)
    byte_col = getattr(node, "col_offset", 0)
    line_text = source.split("\n")[row - 1] if source else ""
    col = len(line_text.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))
    return row - 1, col


def locate(source: str, node: ast.AST, line: int, column: int) -> tuple[int, int]:
    """The file position (line, column) of ``node`` inside an expression that starts at
    ``line``/``column``.
    """
    d_row, col = _chars(source, node)
    if d_row == 0:
        return line, column + col
    return line + d_row, col + 1


class ExpressionTooDeepError(SyntaxError):
    """An expression is nested deeper than ``MAX_DEPTH`` or too long for ``ast`` to read."""


def _bracket_depth(source: str) -> int:
    """The deepest nesting of ``( [ {`` in ``source`` (text inside quotes is skipped)."""
    depth = deepest = 0
    quote = ""
    escaped = False
    for char in source:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in ")]}":
            depth -= 1
    return deepest


def parse_expression(source: str) -> ast.Expression:
    """Parse ``source`` as an expression.

    Raises:
        ExpressionTooDeepError: If the brackets are nested deeper than ``MAX_DEPTH`` or ``ast``
            gives up (recursion, memory).
        SyntaxError: If the text is not a Python-compatible expression.
    """
    if _bracket_depth(source) > MAX_DEPTH:
        raise ExpressionTooDeepError(too_deep_reason())
    try:
        return ast.parse(source, mode="eval")
    except (RecursionError, MemoryError) as exc:
        raise ExpressionTooDeepError(too_deep_reason()) from exc


def _call_label(func: ast.expr) -> str:
    try:
        return f"{ast.unparse(func)}(...)"
    except Exception:  # pragma: no cover - ast.unparse handles every parsed node
        return "(...)"


class _Checker(ast.NodeVisitor):
    def __init__(self, source: str, filename: str, line: int, column: int) -> None:
        self.source = source
        self.filename = filename
        self.line = line
        self.column = column
        self.errors: list[Diagnostic] = []

    def add(self, node: ast.AST, reason: str, fix: str = "") -> None:
        row, col = locate(self.source, node, self.line, self.column)
        self.errors.append(
            Diagnostic(file=self.filename, line=row, column=col, reason=reason, fix=fix)
        )

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.expr_context | ast.boolop):
            return
        allowed = (
            ast.Expression,
            ast.BoolOp,
            ast.UnaryOp,
            ast.IfExp,
            ast.Subscript,
            ast.Slice,
            ast.List,
            ast.Tuple,
        )
        if not isinstance(node, allowed):
            self.add(
                node,
                f"{_describe(node)} is not allowed in an expression.",
                "Allowed: comparison, and/or/not, + - * / // %, in, names, attributes, subscripts, "
                "constants, lists, dicts and the functions " + ", ".join(ALLOWED_FUNCTIONS),
            )
            return
        super().generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, tuple(_UNARY)):
            self.add(node, f'operator "{type(node.op).__name__}" is not allowed in an expression')
        self.visit(node.operand)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, tuple(_BIN)):
            self.add(node, f'operator "{type(node.op).__name__}" is not allowed in an expression')
        self.visit(node.left)
        self.visit(node.right)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            if not isinstance(op, tuple(_CMP)):
                self.add(node, f'operator "{type(op).__name__}" is not allowed in an expression')
        self.visit(node.left)
        for item in node.comparators:
            self.visit(item)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not (node.value is None or isinstance(node.value, bool | int | float | str)):
            self.add(node, f"constant {node.value!r} is not allowed in an expression")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("_"):
            self.add(node, f'name "{node.id}" is not allowed in an expression')

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            self.add(
                node,
                f'attribute "{node.attr}" is not allowed in an expression (names that start with '
                f'"_" are private)',
            )
        self.visit(node.value)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            if key is None:
                self.add(value, 'dict unpacking ("**") is not allowed in an expression')
            else:
                self.visit(key)
            self.visit(value)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in _FUNCTIONS):
            self.add(
                node,
                f'call "{_call_label(func)}" is not allowed in an expression.',
                "Allowed: " + ", ".join(ALLOWED_FUNCTIONS),
            )
            return
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                self.add(arg, 'unpacking ("*") is not allowed in an expression')
            else:
                self.visit(arg)
        for keyword in node.keywords:
            if keyword.arg is None:
                self.add(keyword.value, 'unpacking ("**") is not allowed in an expression')
            else:
                self.visit(keyword.value)


def _describe(node: ast.AST) -> str:
    names = {
        "Lambda": "a lambda",
        "ListComp": "a comprehension",
        "SetComp": "a comprehension",
        "DictComp": "a comprehension",
        "GeneratorExp": "a generator",
        "Await": '"await"',
        "Yield": '"yield"',
        "YieldFrom": '"yield"',
        "NamedExpr": 'the walrus operator ":="',
        "JoinedStr": "an f-string",
        "FormattedValue": "an f-string",
        "Set": "a set",
        "Starred": "unpacking",
    }
    name = type(node).__name__
    return names.get(name, f"{name} syntax")


def check_expression(
    source: str, *, filename: str | None = None, line: int = 1, column: int = 1
) -> list[Diagnostic]:
    """Check that ``source`` is an allowed expression.

    Args:
        source: The expression text.
        filename: The name used in diagnostics.
        line: The line of the first character of ``source`` in its file.
        column: The column of the first character of ``source`` in its file.

    Returns:
        The mistakes found (empty if the expression is allowed).
    """
    name = filename or DEFAULT_FILENAME
    try:
        tree = parse_expression(source)
    except ExpressionTooDeepError:
        return [_too_deep(name, line, column)]
    except SyntaxError as exc:
        reason = exc.msg or "invalid syntax"
        row = line + (exc.lineno or 1) - 1
        col = column + (exc.offset or 1) - 1 if (exc.lineno or 1) == 1 else (exc.offset or 1)
        return [
            Diagnostic(
                file=name,
                line=row,
                column=col,
                reason=f'"{source}" is not a valid expression: {reason}',
            )
        ]
    checker = _Checker(source, name, line, column)
    try:
        checker.visit(tree)
    except RecursionError:
        return [_too_deep(name, line, column)]
    return checker.errors


def _too_deep(file: str, line: int, column: int) -> Diagnostic:
    return Diagnostic(
        file=file,
        line=line,
        column=column,
        reason=too_deep_reason(),
        fix="Split the expression into smaller parts.",
    )


def references(source: str) -> Iterator[tuple[tuple[str, ...], ast.AST]]:
    """The dotted names an expression reads: ``context.x`` gives ``("context", "x")``.

    Names of called functions are not references. ``a.b[0].c`` gives ``("a", "b")`` and ``("...")``
    chains stop at a subscript or a call. The text must be a valid expression.

    Args:
        source: The expression text.

    Yields:
        The chain and its ``ast`` node.
    """
    tree = parse_expression(source)

    def walk(node: ast.AST) -> Iterator[tuple[tuple[str, ...], ast.AST]]:
        if isinstance(node, ast.Attribute | ast.Name):
            chain: list[str] = []
            cur: ast.AST = node
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.append(cur.id)
                yield tuple(reversed(chain)), node
                return
            yield from walk(cur)
            return
        if isinstance(node, ast.Call):
            for arg in node.args:
                yield from walk(arg)
            for keyword in node.keywords:
                yield from walk(keyword.value)
            return
        for child in ast.iter_child_nodes(node):
            yield from walk(child)

    yield from walk(tree)


def evaluate(expression: str | Expression, scope: Mapping[str, Any]) -> Any:
    """Evaluate an expression over a context dict, without ``eval``.

    Args:
        expression: The text, or an :class:`Expression`.
        scope: The names the expression may read (for example ``{"context": {...}, "step":
            {...}}``).
            Attribute access on a mapping reads its key.

    Returns:
        The value.

    Raises:
        SkyeExpressionError: If the expression is not allowed, a name is missing or an operation
            fails.
    """
    source = expression.text if isinstance(expression, Expression) else expression
    problems = check_expression(source)
    if problems:
        raise SkyeExpressionError(problems[0].message, {"expression": source})
    tree = parse_expression(source)
    try:
        return _eval(tree.body, scope)
    except SkyeExpressionError:
        raise
    except (ArithmeticError, TypeError, ValueError, KeyError, IndexError) as exc:
        raise SkyeExpressionError(
            f"cannot evaluate {source!r}: {type(exc).__name__}: {exc}", {"expression": source}
        ) from exc


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        if name in obj:
            return obj[name]
        raise SkyeExpressionError(f'there is no "{name}" in the value')
    if name.startswith("_"):
        raise SkyeExpressionError(f'attribute "{name}" is not allowed')
    try:
        return getattr(obj, name)
    except AttributeError:
        raise SkyeExpressionError(f'there is no "{name}" in the value') from None


def _eval(node: ast.AST, scope: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise SkyeExpressionError(f'name "{node.id}" is not defined')
    if isinstance(node, ast.Attribute):
        return _get(_eval(node.value, scope), node.attr)
    if isinstance(node, ast.Subscript):
        target = _eval(node.value, scope)
        key = node.slice
        if isinstance(key, ast.Slice):
            parts = (
                None if part is None else _eval(part, scope)
                for part in (key.lower, key.upper, key.step)
            )
            return target[slice(*parts)]
        return target[_eval(key, scope)]
    if isinstance(node, ast.BoolOp):
        result: Any = None
        for value in node.values:
            result = _eval(value, scope)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval(node.operand, scope))
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, scope)
        right = _eval(node.right, scope)
        if isinstance(node.op, ast.Mult):
            for seq, count in ((left, right), (right, left)):
                if (
                    isinstance(seq, str | list | tuple)
                    and isinstance(count, int)
                    and count > _MAX_REPEAT
                ):
                    raise SkyeExpressionError(f"repeating a value {count} times is not allowed")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, scope)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, scope)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, scope) else node.orelse, scope)
    if isinstance(node, ast.List):
        return [_eval(item, scope) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(item, scope) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval(k, scope): _eval(v, scope)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
    ):
        args = [_eval(arg, scope) for arg in node.args]
        kwargs = {kw.arg: _eval(kw.value, scope) for kw in node.keywords if kw.arg}
        return _FUNCTIONS[node.func.id](*args, **kwargs)
    raise SkyeExpressionError(f"{type(node).__name__} is not allowed in an expression")
