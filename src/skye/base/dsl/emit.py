"""Write block models back as ``.skye`` text (the opposite of :func:`skye.base.dsl.build`).

``to_text(spec)`` takes a :class:`RouterSpec`, a :class:`FlowSpec` or a :class:`PromptSpec` and
returns text that
:func:`~skye.base.dsl.check_text` accepts and that builds an equal spec again (the round trip is a
test). The text is written
in the style of the examples: one attribute per line, a block on one line when it is short, defaults
left out.

Two things the text does not keep, because the models do not keep them: comments, and the order of
attributes inside a block.
This module reads and writes no file; it is text in, text out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from skye.base.dsl.build import Document
from skye.base.dsl.expressions import Expression
from skye.base.dsl.metadata import format_metadata
from skye.base.dsl.specs import (
    FlowSpec,
    OutputFieldSpec,
    OutputSpec,
    ParallelSpec,
    PromptPartSpec,
    PromptSpec,
    RetrySpec,
    RouterSpec,
    RouteSpec,
    SetSpec,
    StepSpec,
    TargetSpec,
    VariableSpec,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_ENV_REFERENCE = re.compile(r"^\$\{(\w+)\}$")
_WIDTH = 100
_INDENT = "  "


def quote(text: str) -> str:
    """A string literal with the escapes the lexer reads (``\\"``, ``\\\\``, ``\\n``, ``\\t``,
    ``\\r``).
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def value(item: Any, *, env: bool = False) -> str:
    """A value as ``.skye`` text: an expression or reference as written, a string quoted, a map or
    list in brackets.

    Args:
        item: An :class:`Expression`, a string, a number, a bool, a list or a mapping.
        env: When true, a string that is exactly ``${NAME}`` is written as the reference
            ``env.NAME``.
    """
    if isinstance(item, Expression):
        return item.text
    if item is True:
        return "true"
    if item is False:
        return "false"
    if isinstance(item, str):
        match = _ENV_REFERENCE.match(item) if env else None
        return f"env.{match.group(1)}" if match else quote(item)
    if isinstance(item, int | float):
        return repr(item)
    if isinstance(item, Mapping):
        if not item:
            return "{}"
        return "{ " + ", ".join(f"{_key(k)} = {value(v, env=env)}" for k, v in item.items()) + " }"
    if isinstance(item, list | tuple):
        return "[" + ", ".join(value(i, env=env) for i in item) + "]"
    raise ValueError(f"cannot write {item!r} as a .skye value")


def _key(name: str) -> str:
    return name if _IDENTIFIER.match(name) else quote(name)


def _target(name: str) -> str:
    return "end" if name == "end" else quote(name)


def _block(head: str, lines: list[str], depth: int) -> list[str]:
    """``head { a, b }`` on one line when it is short and has no nested block, else one line per
    item.
    """
    pad = _INDENT * depth
    if not lines:
        return [f"{pad}{head} {{}}"]
    flat = f"{pad}{head} {{ {', '.join(lines)} }}"
    if len(flat) <= _WIDTH and all("\n" not in line for line in lines):
        return [flat]
    return [f"{pad}{head} {{", *(f"{pad}{_INDENT}{line}" for line in lines), f"{pad}}}"]


# -- router ------------------------------------------------------------------------------------


def _target_lines(target: TargetSpec) -> list[str]:
    lines = [f"model = {quote(target.model)}", f"provider = {quote(target.provider)}"]
    for name in ("api_key", "api_base", "api_version", "region"):
        item = getattr(target, name)
        if item is not None:
            lines.append(f"{name} = {value(item, env=True)}")
    if target.timeout is not None:
        lines.append(f"timeout = {quote(target.timeout)}")
    if target.max_retries is not None:
        lines.append(f"max_retries = {target.max_retries}")
    if target.weight != 1.0:
        lines.append(f"weight = {target.weight!r}")
    for name in ("tpm", "rpm"):
        item = getattr(target, name)
        if item is not None:
            lines.append(f"{name} = {item}")
    for name in ("cost_per_1k_prompt_tokens", "cost_per_1k_completion_tokens"):
        item = getattr(target, name)
        if item is not None:
            lines.append(f"{name} = {item!r}")
    if target.tags:
        lines.append(f"tags = {value(list(target.tags))}")
    if target.metadata:
        lines.append(f"metadata = {value(dict(target.metadata), env=True)}")
    if target.options:
        lines.append(f"options = {value(dict(target.options), env=True)}")
    return lines


def _shorthand_entry(target: TargetSpec) -> str:
    plain = f"{target.provider}/{target.model}"
    rest = [
        line for line in _target_lines(target) if not line.startswith(("model = ", "provider = "))
    ]
    if not rest:
        return quote(plain)
    return "{ " + ", ".join([f"model = {quote(plain)}", *rest]) + " }"


def _route(route: RouteSpec) -> list[str]:
    if route.fallback_targets:
        entries = ", ".join(_shorthand_entry(t) for t in [*route.targets, *route.fallback_targets])
        return [f"{_INDENT}route {quote(route.alias)} = [{entries}]"]
    out = [f"{_INDENT}route {quote(route.alias)} {{"]
    inner = _INDENT * 2
    if route.strategy:
        out.append(f"{inner}strategy = {quote(route.strategy)}")
    if not route.fallback_on_error:
        out.append(f"{inner}fallback_on_error = false")
    if route.fallback:
        out.append(f"{inner}fallback = {value(list(route.fallback))}")
    for target in route.targets:
        out.extend(_block("target", _target_lines(target), 2))
    out.append(f"{_INDENT}}}")
    return out


def _router(spec: RouterSpec) -> str:
    head = f"router {quote(spec.name)}" if spec.name else "router"
    out = [f"{head} {{"]
    top: list[str] = []
    if spec.strategy:
        top.append(f"strategy = {quote(spec.strategy)}")
    if spec.cooldown is not None:
        top.append(f"cooldown = {quote(spec.cooldown)}")
    if not spec.enable_pre_call_checks:
        top.append("enable_pre_call_checks = false")
    out.extend(f"{_INDENT}{line}" for line in top)
    for route in spec.routes:
        if out[-1] != f"{head} {{":
            out.append("")
        out.extend(_route(route))
    policies: list[str] = []
    for policy in spec.retry_policies:
        items = [f"max_retries = {policy.max_retries}"]
        if policy.retry_after is not None:
            items.append(f"retry_after = {quote(policy.retry_after)}")
        if policy.exponential_backoff:
            items.append("exponential_backoff = true")
        policies.extend(_block(f"retry_policy {quote(policy.error_type)}", items, 1))
    for fails in spec.allowed_fails_policies:
        policies.extend(
            _block(
                f"allowed_fails_policy {quote(fails.error_type)}",
                [f"allowed_fails_per_minute = {fails.allowed_fails_per_minute}"],
                1,
            )
        )
    if policies:
        if out[-1] != f"{head} {{":
            out.append("")
        out.extend(policies)
    out.append("}")
    return "\n".join(out) + "\n"


# -- flow --------------------------------------------------------------------------------------


def _typed(kind: str, default: Any, *, required: bool) -> str:
    return kind if required or default is None else f"{kind}({value(default)})"


def _retry(retry: RetrySpec) -> str:
    if retry.after is None and not retry.backoff:
        return str(retry.max)
    parts = [f"max = {retry.max}"]
    if retry.after is not None:
        parts.append(f"after = {quote(retry.after)}")
    if retry.backoff:
        parts.append("backoff = true")
    return "{ " + ", ".join(parts) + " }"


def _statements(sets: Iterable[SetSpec], emits: Iterable[str]) -> list[str]:
    return [
        *(f"set {s.name} = {value(s.value)}" for s in sets),
        *(f"emit {quote(e)}" for e in emits),
    ]


def _step_lines(step: StepSpec, *, branch: bool) -> list[str]:
    lines: list[str] = []
    if step.run is not None:
        lines.append(f"run = {step.run}")
    if step.input:
        lines.append(f"input = {value(step.input)}")
    if step.foreach is not None:
        lines.append(f"foreach = {value(step.foreach)}")
    if step.timeout is not None:
        lines.append(f"timeout = {quote(step.timeout)}")
    if step.retry is not None:
        lines.append(f"retry = {_retry(step.retry)}")
    if step.max_visits is not None:
        lines.append(f"max_visits = {step.max_visits}")
    lines.extend(_statements(step.set, step.emit))
    if not branch:
        for name in ("next", "on_error", "on_timeout"):
            target = getattr(step, name)
            if target is not None:
                lines.append(f"{name} = {_target(target)}")
    return lines


def _step(step: StepSpec, depth: int, *, branch: bool) -> list[str]:
    return _block(f"step {quote(step.name)}", _step_lines(step, branch=branch), depth)


def _parallel(node: ParallelSpec, depth: int) -> list[str]:
    pad = _INDENT * depth
    out = [f"{pad}parallel {quote(node.name)} {{"]
    inner = _INDENT * (depth + 1)
    if node.join != "all":
        out.append(f"{inner}join = {quote(node.join)}")
    if node.on_branch_error != "cancel":
        out.append(f"{inner}on_branch_error = {quote(node.on_branch_error)}")
    for branch in node.steps:
        out.extend(_step(branch, depth + 1, branch=True))
    for name in ("next", "on_error"):
        target = getattr(node, name)
        if target is not None:
            out.append(f"{inner}{name} = {_target(target)}")
    out.append(f"{pad}}}")
    return out


def _branch(head: str, branch: Any, depth: int) -> list[str]:
    lines = [*_statements(branch.set, branch.emit)]
    if branch.next is not None:
        lines.append(f"next = {_target(branch.next)}")
    pad = _INDENT * depth
    if len(lines) <= 1 and len(f"{pad}{head} {{ {', '.join(lines)} }}") <= _WIDTH:
        return _block(head, lines, depth)
    return [f"{pad}{head} {{", *(f"{pad}{_INDENT}{line}" for line in lines), f"{pad}}}"]


def _choice(node: Any, depth: int) -> list[str]:
    pad = _INDENT * depth
    out = [f"{pad}choice {quote(node.name)} {{"]
    for branch in node.branches:
        out.extend(_branch(f"when {value(branch.when)}", branch, depth + 1))
    if node.otherwise is not None:
        out.extend(_branch("else", node.otherwise, depth + 1))
    out.append(f"{pad}}}")
    return out


def _flow(spec: FlowSpec) -> str:
    out = [f"flow {quote(spec.name)} {{"]
    if spec.context.fields:
        fields = [
            f"{f.name} = {_typed(f.type, f.default, required=f.required)}"
            for f in spec.context.fields
        ]
        out.extend(_block("context", fields, 1))
    for node in spec.nodes:
        if out[-1] != f"flow {quote(spec.name)} {{":
            out.append("")
        if isinstance(node, StepSpec):
            out.extend(_step(node, 1, branch=False))
        elif isinstance(node, ParallelSpec):
            out.extend(_parallel(node, 1))
        else:
            out.extend(_choice(node, 1))
    out.append("}")
    return "\n".join(out) + "\n"


# -- prompt ------------------------------------------------------------------------------------


def _parts(parts: list[PromptPartSpec], depth: int) -> list[str]:
    out: list[str] = []
    pad = _INDENT * depth
    for part in parts:
        if part.kind == "text":
            out.append(f"{pad}text = {quote(part.text or '')}")
        elif part.kind == "placeholder":
            out.append(f"{pad}placeholder {quote(part.name or '')}")
        elif part.kind == "output":  # a conditional output, inside a top-level when
            if part.output is not None:
                out.extend(_output(part.output, depth))
        else:
            if part.kind == "message":
                role = (
                    value(part.role_from) if part.role_from is not None else quote(part.role or "")
                )
                head = f"message {role}"
            elif part.kind == "when":
                head = f"when {value(part.condition)}"
            else:
                head = f"each {part.variable} in {value(part.items)}"
            body = _parts(part.children, depth + 1)
            if (
                len(body) == 1
                and "\n" not in body[0]
                and len(f"{pad}{head} {{ {body[0].strip()} }}") <= _WIDTH
                and "{" not in body[0]
            ):
                out.append(f"{pad}{head} {{ {body[0].strip()} }}")
            else:
                out.extend([f"{pad}{head} {{", *body, f"{pad}}}"])
    return out


def _output_type(item: OutputFieldSpec, depth: int) -> str:
    """The type of a field whose line is at ``depth``; a nested map may span several lines.
    A shape with a default writes it after the shape: ``list({ a = string }, [])``.
    """
    if item.type == "map" and item.fields:
        shape = _output_map(item.fields, depth)
    elif item.type == "list" and item.item_type == "map":
        shape = _output_map(item.fields, depth)
    elif item.type == "list" and item.item_type is not None:
        shape = item.item_type
    else:
        return _typed(item.type, item.default, required=item.required)
    tail = "" if item.default is None else f", {value(item.default)}"
    return f"{item.type}({shape}{tail})"


def _output_entry(item: OutputFieldSpec, depth: int) -> str:
    """``name = type ["description"]`` (the description is the string after the type)."""
    text = f"{_key(item.name)} = {_output_type(item, depth)}"
    return text if item.description is None else f"{text} {quote(item.description)}"


def _output_map(fields: list[OutputFieldSpec], depth: int) -> str:
    """``{ a = string, b = number }`` on one line; one line per field when a field has a
    description (or a nested map does).
    """
    entries = [_output_entry(f, depth + 1) for f in fields]
    if all(f.description is None for f in fields) and not any("\n" in e for e in entries):
        return "{ " + ", ".join(entries) + " }"
    pad = _INDENT * (depth + 1)
    return "{\n" + "\n".join(pad + e for e in entries) + "\n" + _INDENT * depth + "}"


def _output(spec: OutputSpec, depth: int = 1) -> list[str]:
    head = f"output {spec.format_from or quote(spec.format)}"
    if spec.format == "text" and spec.format_from is None:
        style = spec.style_from if spec.style is None else quote(spec.style)
        return _block(head, [] if style is None else [f"style = {style}"], depth)
    if spec.schema_from is not None:
        return _block(head, [f"schema = {spec.schema_from}"], depth)
    entries = [_output_entry(f, depth + 1) for f in spec.fields]
    if all(f.description is None for f in spec.fields):
        return _block(head, entries, depth)
    pad = _INDENT * depth
    return [f"{pad}{head} {{", *(f"{pad}{_INDENT}{e}" for e in entries), f"{pad}}}"]


def _variable_type(spec: VariableSpec) -> str:
    """``string``, ``number(3)``, or a shape (``list({ a = string })``) with its default after it
    (``list({ a = string }, [])``).
    """
    if not spec.structured:
        return _typed(spec.type, spec.default, required=spec.required)
    shape = OutputFieldSpec(
        name=spec.name,
        type=spec.type,
        item_type=spec.item_type,
        fields=list(spec.fields),
        default=spec.default,
        required=spec.required,
    )
    return _output_type(shape, 2)


def _prompt(spec: PromptSpec) -> str:
    out = [f"prompt {quote(spec.name)} {{"]
    if spec.variables:
        items = [
            f"{_key(v.name)} = {_variable_type(v)}"
            + ("" if v.description is None else f" {quote(v.description)}")
            for v in spec.variables
        ]
        one = f"{_INDENT}variables = {{ {', '.join(items)} }}"
        out.extend(
            [one]
            if len(one) <= _WIDTH
            and all(v.description is None for v in spec.variables)
            and not any("\n" in i for i in items)
            else [f"{_INDENT}variables = {{", *(f"{_INDENT * 2}{i}" for i in items), f"{_INDENT}}}"]
        )
    if spec.allow_missing:
        out.append(f"{_INDENT}allow_missing = {value(list(spec.allow_missing))}")
    if spec.output is not None:
        out.extend(_output(spec.output))
    if spec.parts:
        if len(out) > 1:
            out.append("")
        out.extend(_parts(spec.parts, 1))
    out.append("}")
    return "\n".join(out) + "\n"


def to_text(*specs: RouterSpec | FlowSpec | PromptSpec | Document) -> str:
    """The ``.skye`` text of one or more blocks, separated by a blank line.

    Args:
        *specs: Routers, flows and prompts, as :func:`skye.base.dsl.build` returns them (or built
            by hand), or a whole :class:`~skye.base.dsl.Document` (its routers, then its flows,
            then its prompts). A flow that runs ``flow.x``, ``router.x`` or ``prompt.x`` needs
            that block in the same text: pass them together.

    Returns:
        Text that passes :func:`~skye.base.dsl.check_text` (given the same registry names) and
        builds an equal spec. Comments are not kept.

    Raises:
        TypeError: If an argument is not a router, flow or prompt spec or a document.
        ValueError: If a value cannot be written in the language.
    """
    texts: list[str] = []
    for spec in specs:
        if isinstance(spec, Document):
            header = format_metadata(spec.metadata)  # the front matter comes first, then the blocks
            if spec.routers or spec.flows or spec.prompts:
                body = to_text(*spec.routers, *spec.flows, *spec.prompts)
                texts.append(header + "\n" + body if header else body)  # one blank line after it
            elif header:
                texts.append(header)
        elif isinstance(spec, RouterSpec):
            texts.append(_router(spec))
        elif isinstance(spec, FlowSpec):
            texts.append(_flow(spec))
        elif isinstance(spec, PromptSpec):
            texts.append(_prompt(spec))
        else:
            raise TypeError(
                f"to_text writes a RouterSpec, FlowSpec or PromptSpec, not {type(spec).__name__}"
            )
    return "\n".join(texts)


__all__ = ["quote", "to_text", "value"]
