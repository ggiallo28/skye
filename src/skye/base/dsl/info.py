# decision D83
"""Help for ``.skye`` blocks: what a prompt, a router or a flow takes and gives back.

:func:`describe` reads any block (a prompt, a router or a flow) into an info
object: :class:`PromptInfo`, :class:`RouterInfo` or :class:`FlowInfo`; ``skye.dsl`` is its public
path. :func:`describe_prompt` reads a :class:`~skye.base.dsl.PromptSpec` (and, when given, the front
matter of its file) into a :class:`PromptInfo`; :func:`prompt_help` prints it as aligned plain
text. ``BasePromptBuilder.describe`` and ``BasePromptBuilder.help`` do the same for a registered
template, and ``skye prompt info`` on the command line.

It reads specs only, so it lives in ``base`` (the command line in ``utils`` uses it); the public
names are exported by ``skye.prompts``.

The ``roles`` of a prompt are its top-level messages and placeholders in the order written: a
message gives its role (``"system"``), a ``message turn.role`` the expression (``"turn.role"``),
a placeholder its name (``"history"``). A message inside an ``each`` block is marked ``*`` (zero
or more times, ``"user*"``), one inside a ``when`` block ``?`` (only when the condition holds,
``"system?"``); the marks add up from the outside in (``"user*?"``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from skye.base.dsl.specs import (
    ChoiceSpec,
    FlowSpec,
    OutputFieldSpec,
    OutputSpec,
    ParallelSpec,
    PromptPartSpec,
    PromptSpec,
    RouterSpec,
    TargetSpec,
)
from skye.base.validated import Validated, field, validated

__all__ = [
    "FlowInfo",
    "InputInfo",
    "NodeInfo",
    "OutputFieldInfo",
    "OutputInfo",
    "PromptInfo",
    "RouteInfo",
    "RouterInfo",
    "describe",
    "describe_prompt",
    "prompt_help",
]

_INDENT = "  "
_GAP = "  "
_MAX_DEFAULT = 32


@validated
class InputInfo(Validated):
    """One input (declared variable) of a prompt."""

    name: str = field(description="Variable name")
    type: str = field(default="any", description="string, number, bool, list, map or any")
    required: bool = field(
        default=True, description="True when the caller must give it (no default, not optional)"
    )
    default: Any = field(default=None, description="Default value, if any")
    description: str | None = field(default=None, description="What the variable holds")
    allow_missing: bool = field(
        default=False, description="True when it may be left out (allow_missing): it is None"
    )
    item_type: str | None = field(
        default=None, description="list(string) or list({ ... }): the type of the items"
    )
    fields: list[Any] = field(
        default_factory=list,
        description="OutputFieldInfo: the fields of map({ ... }) or of the items of list({ ... })",
    )


@validated
class OutputFieldInfo(Validated):
    """One field of the answer, possibly with nested fields."""

    name: str = field(description="Field name")
    type: str = field(description="string, number, bool, list or map")
    item_type: str | None = field(default=None, description="The items of a list (None: any)")
    required: bool = field(default=True, description="True when there is no default")
    default: Any = field(default=None, description="Default value, if any")
    description: str | None = field(default=None, description="What the field holds")
    fields: list[Any] = field(
        default_factory=list, description="OutputFieldInfo: the fields of a map or list item"
    )


@validated
class OutputInfo(Validated):
    """What the prompt asks the model to answer with."""

    format: str = field(
        default="json", description='json, table, xml, text or "from variable X" (output X { ... })'
    )
    fields: list[OutputFieldInfo] = field(
        default_factory=list, description="The fields of the answer, in order"
    )
    fields_from: str | None = field(
        default=None, description="output { schema = X }: the variable that gives the fields"
    )
    condition: str | None = field(
        default=None,
        description="A conditional output (inside a when): the condition that makes it active",
    )


@validated
class PromptInfo(Validated):
    """What a prompt takes and gives back, for help screens and tools."""

    name: str = field(description="Prompt name")
    title: str | None = field(default=None, description="Front matter title")
    description: str | None = field(default=None, description="Front matter description")
    version: str | None = field(default=None, description="Front matter version")
    tags: list[str] = field(default_factory=list, description="Front matter tags")
    inputs: list[InputInfo] = field(default_factory=list, description="The variables, in order")
    placeholders: list[str] = field(
        default_factory=list, description="Where a message history goes, by name"
    )
    roles: list[str] = field(
        default_factory=list,
        description='Messages and placeholders in order: "system", "history", "user*", "system?"',
    )
    output: OutputInfo | None = field(
        default=None,
        description="The shape of the answer; None for free text or conditional outputs",
    )
    outputs: list[OutputInfo] = field(
        default_factory=list,
        description="The conditional outputs (output inside a when), each with its condition; "
        "at most one is active at render time",
    )


@validated
class RouteInfo(Validated):
    """One route of a router: its alias, its targets and its fallback chain."""

    alias: str = field(description="Alias name of the route")
    targets: list[str] = field(
        default_factory=list, description='The targets, as "provider/model", in order'
    )
    strategy: str | None = field(
        default=None, description="The strategy of the route (None: the router's)"
    )
    fallback: list[str] = field(
        default_factory=list, description="Routes to try, in order, when this route fails"
    )
    fallback_targets: list[str] = field(
        default_factory=list,
        description='The shorthand route "x" = [...]: the entries after the first',
    )


@validated
class RouterInfo(Validated):
    """What a router block holds, for help screens and tools."""

    name: str | None = field(default=None, description="The label of the block, if any")
    title: str | None = field(default=None, description="Front matter title")
    description: str | None = field(default=None, description="Front matter description")
    version: str | None = field(default=None, description="Front matter version")
    tags: list[str] = field(default_factory=list, description="Front matter tags")
    strategy: str | None = field(default=None, description="Default routing strategy")
    cooldown: str | None = field(default=None, description='Cooldown after failures, "60s"')
    routes: list[RouteInfo] = field(default_factory=list, description="The routes, in order")


@validated
class NodeInfo(Validated):
    """One node of a flow: a step, a parallel block or a choice."""

    name: str = field(description="Node name")
    kind: str = field(description="step, parallel or choice")
    run: str | None = field(default=None, description="A step: the Runnable it runs")
    next: str | None = field(default=None, description='The next node, or "end"')
    branches: list[str] = field(
        default_factory=list,
        description="A parallel block: its branch steps; a choice: the next node of each branch",
    )


@validated
class FlowInfo(Validated):
    """What a flow takes (its context) and the nodes it goes through."""

    name: str = field(description="Flow name")
    title: str | None = field(default=None, description="Front matter title")
    description: str | None = field(default=None, description="Front matter description")
    version: str | None = field(default=None, description="Front matter version")
    tags: list[str] = field(default_factory=list, description="Front matter tags")
    start: str | None = field(default=None, description="The first node, where the flow starts")
    inputs: list[InputInfo] = field(
        default_factory=list, description="The declared context fields, in order"
    )
    steps: list[NodeInfo] = field(default_factory=list, description="The nodes, in file order")


# D83
def describe(
    spec: PromptSpec | RouterSpec | FlowSpec, metadata: Mapping[str, Any] | None = None
) -> PromptInfo | RouterInfo | FlowInfo:
    """What a block of a ``.skye`` file takes and gives back, for every kind of block.

    Args:
        spec: A prompt, router or flow, from a ``Document`` (``document.prompt(name)``,
            ``document.routers[0]``, ``document.flows[0]``).
        metadata: The front matter of its file (``Document.metadata``).

    Returns:
        A :class:`PromptInfo` (as :func:`describe_prompt`), a :class:`RouterInfo` (the routes
        with their targets and fallbacks) or a :class:`FlowInfo` (the context fields and the
        nodes).

    Raises:
        TypeError: If ``spec`` is not a prompt, router or flow spec.

    Example:
        >>> from skye.base.dsl import build
        >>> document = build('router "r" {\n  route "a" = ["openai/gpt-4o-mini"]\n}\n')
        >>> describe(document.routers[0]).routes[0].targets
        ['openai/gpt-4o-mini']
    """
    if isinstance(spec, PromptSpec):
        return describe_prompt(spec, metadata)
    if isinstance(spec, RouterSpec):
        return _describe_router(spec, metadata)
    if isinstance(spec, FlowSpec):
        return _describe_flow(spec, metadata)
    raise TypeError(
        f"describe() takes a PromptSpec, RouterSpec or FlowSpec, not {type(spec).__name__}"
    )


def _target(target: TargetSpec) -> str:
    return f"{target.provider}/{target.model}"


def _describe_router(spec: RouterSpec, metadata: Mapping[str, Any] | None) -> RouterInfo:
    routes = [
        RouteInfo(
            alias=route.alias,
            targets=[_target(t) for t in route.targets],
            strategy=route.strategy,
            fallback=list(route.fallback),
            fallback_targets=[_target(t) for t in route.fallback_targets],
        )
        for route in spec.routes
    ]
    return RouterInfo(
        name=spec.name,
        strategy=spec.strategy,
        cooldown=spec.cooldown,
        routes=routes,
        **header_fields(metadata),
    )


def _node_info(node: Any) -> NodeInfo:
    if isinstance(node, ParallelSpec):
        return NodeInfo(
            name=node.name,
            kind="parallel",
            next=node.next,
            branches=[step.name for step in node.steps],
        )
    if isinstance(node, ChoiceSpec):
        branches = [b.next for b in node.branches if b.next is not None]
        if node.otherwise is not None and node.otherwise.next is not None:
            branches.append(node.otherwise.next)
        return NodeInfo(name=node.name, kind="choice", branches=branches)
    return NodeInfo(name=node.name, kind="step", run=node.run, next=node.next)


def _describe_flow(spec: FlowSpec, metadata: Mapping[str, Any] | None) -> FlowInfo:
    inputs = [
        InputInfo(name=f.name, type=f.type, required=f.required, default=f.default)
        for f in spec.context.fields
    ]
    return FlowInfo(
        name=spec.name,
        start=spec.start,
        inputs=inputs,
        steps=[_node_info(node) for node in spec.nodes],
        **header_fields(metadata),
    )


def describe_prompt(spec: PromptSpec, metadata: Mapping[str, Any] | None = None) -> PromptInfo:
    """What a ``.skye`` prompt takes and gives back.

    Args:
        spec: The prompt, from :func:`skye.prompts.load_prompt` or ``Document.prompt``.
        metadata: The front matter of its file (``Document.metadata``); gives the title,
            description, version and tags.

    Returns:
        The inputs (declared variables with type, default and description), the placeholders,
        the sequence of messages and the output.
    """
    allowed = set(spec.allow_missing)
    inputs = [
        InputInfo(
            name=v.name,
            type=v.type,
            required=v.required and v.name not in allowed,
            default=v.default,
            description=v.description,
            allow_missing=v.name in allowed,
            item_type=v.item_type,
            fields=_output_fields(v.fields),
        )
        for v in spec.variables
    ]
    output = _output_info(spec.output, None) if spec.output is not None else None
    outputs = [
        _output_info(out, _condition_text(conditions))
        for conditions, out in spec.output_variants()
        if conditions
    ]
    return PromptInfo(
        name=spec.name,
        inputs=inputs,
        placeholders=_placeholders(spec.parts),
        roles=_roles(spec.parts, ""),
        output=output,
        outputs=outputs,
        **header_fields(metadata),
    )


def _output_info(out: OutputSpec, condition: str | None) -> OutputInfo:
    return OutputInfo(
        format=out.format if out.format_from is None else f"from variable {out.format_from}",
        fields=_output_fields(out.fields),
        fields_from=out.schema_from,
        condition=condition,
    )


def _condition_text(conditions: Sequence[Any]) -> str:
    """The conditions of the ``when`` blocks around an output, joined with ``and``."""
    texts = [str(getattr(c, "text", c)) for c in conditions]
    if len(texts) > 1:
        texts = [f"({t})" if " or " in t else t for t in texts]
    return " and ".join(texts)


def header_fields(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``title``, ``description``, ``version`` and ``tags`` of a front matter."""
    meta = metadata or {}
    out: dict[str, Any] = {}
    for key in ("title", "description", "version"):
        if meta.get(key) is not None:
            out[key] = str(meta[key])
    tags = meta.get("tags")
    if isinstance(tags, list | tuple):
        out["tags"] = [str(t) for t in tags]
    return out


def _output_fields(fields: Sequence[OutputFieldSpec]) -> list[OutputFieldInfo]:
    return [
        OutputFieldInfo(
            name=f.name,
            type=f.type,
            item_type=f.item_type,
            required=f.required,
            default=f.default,
            description=f.description,
            fields=_output_fields(f.fields),
        )
        for f in fields
    ]


def _placeholders(parts: Iterable[PromptPartSpec]) -> list[str]:
    names: list[str] = []
    for part in parts:
        if part.kind == "placeholder" and part.name and part.name not in names:
            names.append(part.name)
        names.extend(n for n in _placeholders(part.children) if n not in names)
    return names


def _roles(parts: Iterable[PromptPartSpec], mark: str) -> list[str]:
    out: list[str] = []
    for part in parts:
        if part.kind == "message":
            role = part.role if part.role is not None else getattr(part.role_from, "text", "?")
            out.append(f"{role}{mark}")
        elif part.kind == "placeholder" and part.name:
            out.append(f"{part.name}{mark}")
        elif part.kind == "each":
            out.extend(_roles(part.children, mark + "*"))
        elif part.kind == "when":
            out.extend(_roles(part.children, mark + "?"))
    return out


def fields_from_json_schema(schema: Mapping[str, Any]) -> list[OutputFieldInfo]:
    """The fields of an object JSON Schema (``set_output_schema``), nested ones included."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return []
    required = set(schema.get("required") or [])
    out: list[OutputFieldInfo] = []
    for name, sub in properties.items():
        if not isinstance(sub, Mapping):
            continue
        kind = _json_type(sub)
        item_type: str | None = None
        nested: list[OutputFieldInfo] = []
        if kind == "list" and isinstance(sub.get("items"), Mapping):
            item_type = _json_type(sub["items"])
            nested = fields_from_json_schema(sub["items"])
        elif kind == "map":
            nested = fields_from_json_schema(sub)
        out.append(
            OutputFieldInfo(
                name=str(name),
                type=kind,
                item_type=None if item_type == "any" else item_type,
                required=name in required,
                default=sub.get("default"),
                description=sub.get("description"),
                fields=nested,
            )
        )
    return out


def _json_type(schema: Mapping[str, Any]) -> str:
    kind = schema.get("type")
    names = {
        "string": "string",
        "number": "number",
        "integer": "number",
        "boolean": "bool",
        "array": "list",
        "object": "map",
    }
    if isinstance(kind, str) and kind in names:
        return names[kind]
    if "properties" in schema:
        return "map"
    return "any"


# -- text ---------------------------------------------------------------------------------------


def prompt_help(spec: PromptSpec | PromptInfo, metadata: Mapping[str, Any] | None = None) -> str:
    """The help of a prompt as aligned plain text (no colours).

    Sections: a header ``name — title (version)``, the description and tags, ``Inputs`` (one row
    per variable: name, type, ``required`` / ``optional`` / ``= default``, description; the
    fields of a structured variable indented below it),
    ``History`` (the placeholders), ``Messages`` (the roles in order, see the module docstring)
    and ``Output`` (the format and the fields, nested ones indented).

    Args:
        spec: The prompt, or a :class:`PromptInfo` already made.
        metadata: The front matter of its file (ignored when ``spec`` is a ``PromptInfo``).

    Returns:
        The text, ending with a newline.
    """
    info = spec if isinstance(spec, PromptInfo) else describe_prompt(spec, metadata)
    head = info.name
    if info.title:
        head += f" — {info.title}"
    if info.version:
        head += f" ({info.version})"
    lines = [head]
    if info.description:
        lines.append(info.description)
    if info.tags:
        lines.append("Tags: " + ", ".join(info.tags))

    lines += ["", "Inputs"]
    rows = []
    for item in info.inputs:
        kind = item.type if item.item_type is None else f"list of {item.item_type}"
        need = _need(item.required, item.allow_missing, item.default)
        rows.append([item.name, kind, need, item.description or ""])
        rows.extend(_field_rows(item.fields, 1))
    lines += _table(rows) if rows else [f"{_INDENT}(none)"]

    lines += ["", "History"]
    lines += [f"{_INDENT}{name}" for name in info.placeholders] or [f"{_INDENT}(none)"]

    lines += ["", "Messages"]
    lines.append(_INDENT + (", ".join(info.roles) if info.roles else "(none)"))

    output = info.output
    if output is not None:
        lines += ["", f"Output ({output.format})", *_output_lines(output)]
    elif info.outputs:
        for variant in info.outputs:
            head = f"Output (when {variant.condition}): {variant.format}"
            lines += ["", head, *_output_lines(variant)]
    else:
        lines += ["", "Output", f"{_INDENT}free text"]
    return "\n".join(lines) + "\n"


def _output_lines(output: OutputInfo) -> list[str]:
    if output.format == "text":
        return [f"{_INDENT}plain text"]
    if output.fields_from is not None:
        return [f"{_INDENT}fields from variable {output.fields_from}"]
    rows = list(_field_rows(output.fields, 0))
    return _table(rows) if rows else [f"{_INDENT}(any)"]


def _need(required: bool, allow_missing: bool, default: Any) -> str:
    if default is not None:
        text = json.dumps(default, ensure_ascii=False, default=str)
        if len(text) > _MAX_DEFAULT:
            text = text[: _MAX_DEFAULT - 3] + "..."
        return f"= {text}"
    if required:
        return "required"
    return "optional"


def _field_rows(fields: Sequence[OutputFieldInfo], depth: int) -> Iterable[list[str]]:
    for f in fields:
        kind = f.type if f.item_type is None else f"list of {f.item_type}"
        yield [
            _INDENT * depth + f.name,
            kind,
            _need(f.required, False, f.default),
            f.description or "",
        ]
        yield from _field_rows(f.fields, depth + 1)


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[col]) for row in rows) for col in range(len(rows[0]))]
    out = []
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=True)]
        out.append((_INDENT + _GAP.join(cells)).rstrip())
    return out
