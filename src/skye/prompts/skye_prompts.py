# decision D60, decision D70
"""Renderer for the ``prompt`` block of ``.skye`` files (version 1).

``base`` parses and checks a ``prompt`` block into a :class:`~skye.base.dsl.PromptSpec`; this
module turns that spec plus the caller's variables into a list of :class:`SkyeMessage` with real
roles. ``base`` has no template engine, so rendering lives here.

Semantics:
    * Structured variables (``list(string)``, ``list({ ... })``, ``map({ ... })``): the value
      given is checked against the shape, and one :class:`ValidationError` lists every mistake
      by path (``categories[1].name: missing``, ``examples[0].text: expected string, got int``).
      ``number`` takes int or float, ``bool`` only a bool; a missing (or ``None``) optional field
      gets its default in a copy, so the caller's data is never changed; keys the shape does not
      declare are kept.
    * Variables: a declared default applies when the caller does not provide the variable. A
      variable with no default that is not in ``allow_missing`` and not provided is an error: one
      ``ValueError`` (a :class:`ValidationError`) names every missing variable, sorted. A variable
      in ``allow_missing`` that is absent (and has no default) is ``None``: falsy in a ``when``, no
      items in an ``each``, empty text in ``{{ }}``. Provided variables that are not declared are
      ignored (except by ``placeholder``, see below).
    * ``when`` conditions and ``each`` items are evaluated with :func:`skye.base.dsl.evaluate` over
      a scope of the variables plus the loop variables. Every declared variable is always in the
      scope (provided, default, or ``None``), so a missing top-level name cannot happen. A key
      missing inside a mapping (``example.reasoning`` on an item without ``reasoning``) reads as
      ``None``, as in Jinja: the scope is copied along that path with the key filled in before
      ``evaluate`` runs. Attribute access on other objects stays strict. ``true``, ``false`` and
      ``none`` are literals unless a variable of that name exists.
    * ``text`` parts are rendered by :func:`skye.prompts.engine.render_template` with the scope
      (a top-level ``None`` is passed as ``""``) and the caller's filters. Inside a message the
      text parts, including those inside nested ``when`` / ``each`` blocks, are joined in order
      with ``"\\n"``; a part that renders to ``""`` is dropped, and a message whose joined text is
      blank is skipped.
    * ``message "<role>"`` gives a :class:`SystemMessage`, :class:`UserMessage` or
      :class:`AssistantMessage`; ``message turn.role`` evaluates the role, and a role that is not
      ``system``, ``user`` or ``assistant`` raises :class:`ValidationError`.
    * ``placeholder "name"`` inserts ``history[name]`` when given, else the provided variable
      ``name`` (declared or not); each entry is a :class:`SkyeMessage` or a mapping read with
      :meth:`SkyeMessage.from_dict`. Nothing is inserted when neither is present (or it is
      ``None``).

    * ``output "json" | "table" | "xml" { ... }`` (or ``output "text" { style = "..." }``): :func:`output_instructions`
      writes the instructions that ask for an answer of that shape and format, and
      :func:`render_prompt` appends them as the last text of the last user message (a new user
      message when the prompt has none). ``output { schema = VAR }`` reads the fields from the
      map variable ``VAR`` at render time, and ``output VAR { ... }`` the format from the string
      variable ``VAR``. A string after a field type is its description, written into the
      instructions (the JSON Schema ``description``, the table column list, the XML skeleton).
      Output blocks may instead sit inside top-level ``when`` blocks (conditional outputs):
      :func:`active_output` picks the one whose conditions hold (none: free text; more than one
      raises :class:`ValidationError`).

A flow step reaches a prompt as ``run = prompt.NAME``; :class:`PromptRunnable` adapts a spec to the
``Runnable`` Port so the flow runtime can hold it without importing this package's internals.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from skye.base.dsl import Expression, OutputSpec, PromptPartSpec, PromptSpec, build, evaluate
from skye.base.dsl.expressions import references
from skye.base.dsl.shapes import conform
from skye.base.exceptions import ValidationError
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.base.prompt_parts import OutputSchema, PromptParts
from skye.prompts.engine import render_template
from skye.prompts.output_format import (
    OUTPUT_FORMATS,
    fields_from_value,
    fields_schema,
    format_instructions,
)

logger = logging.getLogger(__name__)

ROLES: tuple[str, ...] = ("system", "user", "assistant")
_MESSAGE_TYPES: dict[str, Callable[..., SkyeMessage]] = {
    "system": SystemMessage,
    "user": UserMessage,
    "assistant": AssistantMessage,
}
_LITERALS: dict[str, Any] = {"true": True, "false": False, "none": None}

History = Mapping[str, Sequence[SkyeMessage | Mapping[str, Any]]]
Filters = Mapping[str, Callable[..., Any]]


def load_prompt(text: str, name: str | None = None) -> PromptSpec:
    """Build a ``.skye`` text and return one of its prompts.

    Args:
        text: The ``.skye`` text.
        name: The prompt to return; ``None`` returns the only prompt of the text.

    Returns:
        The prompt spec.

    Raises:
        ValidationError: If the text has mistakes; the message lists every diagnostic and
            ``details["diagnostics"]`` holds them formatted as ``file:line:col message``.
        KeyError: If there is no prompt ``name`` (or, with no name, not exactly one prompt).
    """
    document = build(text)
    if document.diagnostics:
        lines = [d.format() for d in document.diagnostics]
        raise ValidationError(
            "Invalid .skye prompt:\n" + "\n".join(lines),
            field="text",
            value=name,
            diagnostics=lines,
        )
    return document.prompt(name)


def render_prompt(
    spec: PromptSpec,
    variables: Mapping[str, Any],
    *,
    history: History | None = None,
    filters: Filters | None = None,
) -> list[SkyeMessage]:
    """Render a prompt spec into messages with real roles.

    Args:
        spec: The prompt, from :func:`load_prompt` or ``Document.prompt``.
        variables: The values of the declared variables (others are ignored, except by a
            ``placeholder`` of the same name).
        history: Messages to insert at each ``placeholder``, by placeholder name.
        filters: Extra filters for the ``{{ }}`` interpolation.

    Returns:
        The messages, in order.

    Raises:
        ValidationError: A required variable is missing (the message starts with ``Missing
            required variable`` and names all of them), the value of a structured variable does
            not match its shape (``Invalid variables``, every mistake by path), a role is invalid,
            a history entry is not a message, or an ``each`` is over something that is not a list.
    """
    messages, scope = _render_messages(spec, variables, history, filters)
    instructions = output_instructions(spec, scope)
    if instructions:
        _append_instructions(messages, instructions)
    logger.debug(
        "prompt rendered",
        extra={"prompt": spec.name, "messages": len(messages)},
    )
    return messages


# Requirement 33.9, decisions D81, D101
def render_parts(
    spec: PromptSpec,
    variables: Mapping[str, Any],
    *,
    history: History | None = None,
    filters: Filters | None = None,
) -> PromptParts:
    """Render a prompt spec into provider-agnostic parts.

    Give the result to ``client.complete(parts, model=...)``: the model adapter puts the system
    text and the output schema in the provider's own fields, or falls back to the text.

    Args:
        spec: The prompt, from :func:`load_prompt` or ``Document.prompt``.
        variables: The values of the declared variables, as for :func:`render_prompt`.
        history: Messages to insert at each ``placeholder``, by placeholder name.
        filters: Extra filters for the ``{{ }}`` interpolation.

    Returns:
        The parts: ``system`` is the text of the system messages (joined with a blank line;
        ``None`` when there is none), ``messages`` the other messages in order, ``output`` the
        JSON Schema of the active ``json`` output block as an :class:`OutputSchema` (named after
        the prompt; ``None`` for free text, ``table`` and ``xml``) and ``fallback_text`` its
        instructions (``None`` without an output block). Unlike :func:`render_prompt`, the
        instructions are not appended to the last user message.

    Raises:
        ValidationError: As :func:`render_prompt` and :func:`output_instructions`.

    Example:
        >>> spec = load_prompt('prompt "p" {\n  message "user" { text = "Hi" }\n}\n')
        >>> render_parts(spec, {}).messages[0].content
        'Hi'
    """
    messages, scope = _render_messages(spec, variables, history, filters)
    active = _active_fields(spec, scope)
    output: OutputSchema | None = None
    fallback: str | None = None
    if active is not None:
        output_format, schema = active
        fallback = format_instructions(schema, output_format, spec.name)
        if output_format == "json":
            output = OutputSchema(name=schema_name(spec.name), schema=schema)
    return split_system(messages, output, fallback)


def output_json_schema(
    spec: PromptSpec, variables: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """The JSON Schema of the active ``output`` block of a prompt, or ``None`` (free text).

    The schema is the same whatever the format (``json``, ``table`` or ``xml``): an object with
    one property per field, its description, and ``required`` for the fields without a default.

    Args:
        spec: The prompt.
        variables: The values of the variables, read as by :func:`output_instructions`.

    Raises:
        ValidationError: As :func:`output_instructions`.
    """
    active = _active_fields(spec, variables)
    return active[1] if active is not None else None


def schema_name(name: str) -> str:
    """A prompt or template name as an output schema name (letters, digits, ``_`` and ``-``)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "output"


def split_system(
    messages: Sequence[SkyeMessage],
    output: OutputSchema | None = None,
    fallback_text: str | None = None,
) -> PromptParts:
    """Parts from rendered messages: the system texts apart, the other messages in order."""
    system = [m.content for m in messages if isinstance(m, SystemMessage) and m.content]
    rest = tuple(m for m in messages if not isinstance(m, SystemMessage))
    return PromptParts(
        messages=rest,
        system="\n\n".join(system) if system else None,
        output=output,
        fallback_text=fallback_text or None,
    )


def _render_messages(
    spec: PromptSpec,
    variables: Mapping[str, Any],
    history: History | None,
    filters: Filters | None,
) -> tuple[list[SkyeMessage], dict[str, Any]]:
    """The messages of the prompt (without output instructions) and the scope they used."""
    scope = _scope(spec, variables)
    renderer = _Renderer(variables, history or {}, filters)
    messages: list[SkyeMessage] = []
    renderer.top(spec.parts, scope, messages)
    return messages, scope


def active_output(
    spec: PromptSpec, variables: Mapping[str, Any] | None = None
) -> OutputSpec | None:
    """The output block that applies to these variables, or ``None``.

    The unconditional ``output`` block always applies. A conditional one (an ``output`` inside a
    top-level ``when``) applies when the conditions of its ``when`` blocks hold; a variable with
    no value takes its declared default.

    Args:
        spec: The prompt.
        variables: The values of the variables.

    Returns:
        The active output block, or ``None`` when there is none (free text).

    Raises:
        ValidationError: More than one conditional output is active (the message names their
            conditions).
    """
    variants = spec.output_variants()
    if not variants or not variants[0][0]:  # none, or the unconditional block
        return variants[0][1] if variants else None
    given = variables or {}
    scope: dict[str, Any] = dict(_LITERALS)
    for var in spec.variables:
        scope[var.name] = given[var.name] if given.get(var.name) is not None else var.default
    active = [
        (conditions, out)
        for conditions, out in variants
        if all(_value(condition, scope) for condition in conditions)
    ]
    if len(active) > 1:
        names = ["when " + " and ".join(str(c.text) for c in conds) for conds, _ in active]
        raise ValidationError(
            f"Prompt {spec.name!r}: {len(active)} output blocks are active at once "
            f"({'; '.join(names)}); make their conditions exclude each other",
            field="output",
            value=names,
            prompt=spec.name,
        )
    return active[0][1] if active else None


def output_instructions(spec: PromptSpec, variables: Mapping[str, Any] | None = None) -> str:
    """The instructions for the active ``output`` block of a prompt ("" when there is none).

    The active block is the one :func:`active_output` gives: the unconditional block, or the
    conditional one (inside a top-level ``when``) whose conditions hold.

    Args:
        spec: The prompt.
        variables: The values of the variables; read by the conditions of conditional outputs,
            by ``output { schema = VAR }``, which takes its fields from ``VAR``, and by
            ``output VAR { ... }``, which takes its format from ``VAR`` (each from its declared
            default when it has no value).

    Returns:
        Plain-English text that asks for a single JSON object (with the JSON Schema and an
        example), a Markdown table (header, separator and the type of each column) or XML (a
        skeleton whose root element is the prompt name in snake_case). The same spec gives the
        same text.

    Raises:
        ValidationError: ``schema = VAR`` and ``VAR`` is missing or not a valid map of types,
            ``output VAR`` and ``VAR`` is missing or not json, table or xml, a table would
            have a list or map column (the message names it), or more than one conditional
            output is active.
    """
    active = _active_fields(spec, variables)
    if active is None:
        return ""
    output_format, schema = active
    return format_instructions(schema, output_format, spec.name)


def _active_fields(
    spec: PromptSpec, variables: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]] | None:
    """The format and the JSON Schema of the active output block, or ``None``."""
    output = active_output(spec, variables)
    if output is None:
        return None
    output_format: str = output.format
    if output.format_from is not None:
        name = output.format_from
        output_format = str(_output_variable(spec, variables, name, "format"))
        if output_format not in OUTPUT_FORMATS:
            raise ValidationError(
                f"Prompt {spec.name!r}: the output format comes from the variable {name!r}, "
                f"whose value {output_format!r} is not one of json, table, xml or text",
                field=name,
                value=output_format,
                supported=list(OUTPUT_FORMATS),
                prompt=spec.name,
            )
    if output_format == "text":  # a plain answer: the fields (or the schema) are not read
        style = output.style
        if output.style_from is not None:
            style = _output_variable(spec, variables, output.style_from, "style")
        return output_format, {"style": style}
    fields = list(output.fields)
    if output.schema_from is not None:
        name = output.schema_from
        fields = fields_from_value(_output_variable(spec, variables, name, "schema"), name)
    return output_format, fields_schema(fields)


def _output_variable(
    spec: PromptSpec, variables: Mapping[str, Any] | None, name: str, what: str
) -> Any:
    """The value of the variable that gives the output ``schema`` or ``format``, or its default."""
    value = (variables or {}).get(name)
    if value is None:
        value = next((v.default for v in spec.variables if v.name == name), None)
    if value is None:
        raise ValidationError(
            f"Prompt {spec.name!r}: the output {what} comes from the variable {name!r}, "
            "which has no value",
            field="variables",
            value=name,
            prompt=spec.name,
        )
    return value


def _append_instructions(messages: list[SkyeMessage], text: str) -> None:
    """Add ``text`` at the end of the last user message, or as a new user message."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, UserMessage):
            content = f"{message.content}\n\n{text}" if message.content else text
            messages[index] = dataclasses.replace(message, content=content)
            return
    messages.append(UserMessage(content=text))


class PromptRunnable:
    """A prompt as a ``Runnable``: variables in, messages out (``run = prompt.NAME`` in a flow).

    Args:
        spec: The prompt.
        filters: Extra filters for the ``{{ }}`` interpolation.

    The input of :meth:`invoke` is the mapping of variables; a ``placeholder`` reads its history
    from the variable of the same name.
    """

    def __init__(self, spec: PromptSpec, *, filters: Filters | None = None) -> None:
        """Keep the spec and the filters."""
        self.spec = spec
        self.filters = filters

    @property
    def name(self) -> str:
        """The prompt name."""
        return self.spec.name

    async def invoke(self, input: Mapping[str, Any]) -> list[SkyeMessage]:
        """Render the prompt with ``input`` as the variables."""
        return render_prompt(self.spec, input, filters=self.filters)

    async def ainvoke(self, input: Mapping[str, Any]) -> list[SkyeMessage]:
        """Alias of :meth:`invoke`."""
        return await self.invoke(input)

    def __repr__(self) -> str:
        return f"PromptRunnable(name={self.spec.name!r})"


# ---------------------------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------------------------


def _scope(spec: PromptSpec, variables: Mapping[str, Any]) -> dict[str, Any]:
    """The declared variables with defaults applied; raise naming every missing required one."""
    allow = set(spec.allow_missing)
    scope: dict[str, Any] = {}
    missing: list[str] = []
    errors: list[str] = []
    for var in spec.variables:
        if var.name in variables:
            value = variables[var.name]
            if var.structured and value is not None:  # checked, defaults filled in a copy
                value = conform(var.type, var.item_type, var.fields, value, var.name, errors)
            scope[var.name] = value
        elif not var.required:
            scope[var.name] = copy.deepcopy(var.default) if var.structured else var.default
        elif var.name in allow:
            scope[var.name] = None
        else:
            missing.append(var.name)
    if missing:
        names = sorted(missing)
        label = "variable" if len(names) == 1 else "variables"
        raise ValidationError(
            f"Missing required {label} for prompt {spec.name!r}: {', '.join(names)}",
            field="variables",
            value=names,
            prompt=spec.name,
        )
    if errors:
        raise ValidationError(
            f"Invalid variables for prompt {spec.name!r}: {'; '.join(errors)}",
            field="variables",
            value=errors,
            prompt=spec.name,
        )
    return {**{k: v for k, v in _LITERALS.items() if k not in scope}, **scope}


def _fill_missing_keys(text: str, scope: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``scope`` where every key the expression reads from a mapping exists.

    A missing key becomes ``None`` (an intermediate missing key becomes ``{}``), so ``evaluate``
    reads it like Jinja reads an undefined value. ``scope`` itself is never changed; it is
    returned as is when nothing is missing.
    """
    out: dict[str, Any] | None = None
    for chain, _node in references(text):
        missing_at = _first_missing(chain, out if out is not None else scope)
        if missing_at is None:
            continue
        if out is None:
            out = dict(scope)
        container: dict[str, Any] = out
        for key in chain[:missing_at]:
            child = dict(container[key])
            container[key] = child
            container = child
        for key in chain[missing_at:-1]:
            child = {}
            container[key] = child
            container = child
        container[chain[-1]] = None
    return out if out is not None else scope


def _first_missing(chain: tuple[str, ...], scope: Mapping[str, Any]) -> int | None:
    """The index of the first key of ``chain`` missing from a mapping, or ``None``."""
    if chain[0] not in scope:
        return None  # an undeclared name; build() rejects it, let evaluate report it
    obj = scope[chain[0]]
    for index, key in enumerate(chain[1:], start=1):
        if not isinstance(obj, Mapping):
            return None
        if key not in obj:
            return index
        obj = obj[key]
    return None


def _value(expression: Any, scope: dict[str, Any]) -> Any:
    """Evaluate an :class:`Expression`; a literal value is returned as is."""
    if isinstance(expression, Expression):
        return evaluate(expression, _fill_missing_keys(expression.text, scope))
    return expression


def _items(part: PromptPartSpec, scope: dict[str, Any]) -> Iterable[Any]:
    value = _value(part.items, scope)
    if value is None:
        return ()
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise ValidationError(
            f"each {part.variable} in ...: the value is not a list ({type(value).__name__})",
            field="each",
            value=value,
        )
    if isinstance(value, Mapping):
        # A map is looped over as entries:
        # `each entry in data { "{{ entry.key }}: {{ entry.value }}" }`.
        return [{"key": key, "value": item} for key, item in value.items()]
    return list(value)


def _loop_scopes(part: PromptPartSpec, scope: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """The scope of each turn of an ``each``: the loop variable plus ``loop`` (index, index0,
    first, last, length).
    """
    items = list(_items(part, scope))
    length = len(items)
    for index0, item in enumerate(items):
        loop = {
            "index": index0 + 1,
            "index0": index0,
            "first": index0 == 0,
            "last": index0 == length - 1,
            "length": length,
        }
        yield {**scope, str(part.variable): item, "loop": loop}


class _Renderer:
    def __init__(
        self, variables: Mapping[str, Any], history: History, filters: Filters | None
    ) -> None:
        self.variables = variables
        self.history = history
        self.filters = filters

    def top(
        self, parts: Sequence[PromptPartSpec], scope: dict[str, Any], out: list[SkyeMessage]
    ) -> None:
        for part in parts:
            if part.kind == "message":
                self.message(part, scope, out)
            elif part.kind == "placeholder":
                self.placeholder(part, out)
            elif part.kind == "when":
                if _value(part.condition, scope):
                    self.top(part.children, scope, out)
            elif part.kind == "each":
                for inner in _loop_scopes(part, scope):
                    self.top(part.children, inner, out)
            elif part.kind == "output":
                pass  # a conditional output: render_prompt appends the active one
            else:
                raise ValidationError(
                    f"a {part.kind!r} part is only allowed inside a message",
                    field="parts",
                    value=part.kind,
                )

    def message(self, part: PromptPartSpec, scope: dict[str, Any], out: list[SkyeMessage]) -> None:
        role = part.role if part.role_from is None else _value(part.role_from, scope)
        if role not in ROLES:
            raise ValidationError(
                f"Invalid role {role!r}: use one of {', '.join(ROLES)}",
                field="role",
                value=role,
                supported=list(ROLES),
            )
        texts: list[str] = []
        self.texts(part.children, scope, texts)
        content = "\n".join(texts)
        if content.strip():
            out.append(_MESSAGE_TYPES[str(role)](content=content))

    def texts(self, parts: Sequence[PromptPartSpec], scope: dict[str, Any], out: list[str]) -> None:
        for part in parts:
            if part.kind == "text":
                rendered = self.render(part.text or "", scope)
                if rendered:
                    out.append(rendered)
            elif part.kind == "when":
                if _value(part.condition, scope):
                    self.texts(part.children, scope, out)
            elif part.kind == "each":
                for inner in _loop_scopes(part, scope):
                    self.texts(part.children, inner, out)
            else:
                raise ValidationError(
                    f"a {part.kind!r} part is not allowed inside a message",
                    field="parts",
                    value=part.kind,
                )

    def render(self, text: str, scope: dict[str, Any]) -> str:
        if "{{" not in text and "{%" not in text and "{#" not in text:
            return text
        context = {k: ("" if v is None else v) for k, v in scope.items()}
        return render_template(text, context, self.filters)

    def placeholder(self, part: PromptPartSpec, out: list[SkyeMessage]) -> None:
        name = str(part.name)
        entries: Any = self.history[name] if name in self.history else self.variables.get(name)
        if entries is None:
            return
        if isinstance(entries, str | bytes | Mapping) or not isinstance(entries, Iterable):
            raise ValidationError(
                f"placeholder {name!r} needs a list of messages, got {type(entries).__name__}",
                field="history",
                value=name,
            )
        for entry in entries:
            if isinstance(entry, SkyeMessage):
                out.append(entry)
            elif isinstance(entry, Mapping):
                out.append(SkyeMessage.from_dict(entry))
            else:
                raise ValidationError(
                    f"placeholder {name!r}: an entry is not a message or a mapping "
                    f"({type(entry).__name__})",
                    field="history",
                    value=name,
                )


__all__ = [
    "ROLES",
    "PromptRunnable",
    "active_output",
    "load_prompt",
    "output_instructions",
    "output_json_schema",
    "render_parts",
    "render_prompt",
    "schema_name",
    "split_system",
]
