# Requirement 54.21, D88, D50, D49
"""Draw a flow or a router as a Mermaid diagram, text in and text out.

The diagram is generated from the model, never parsed back: ``to_mermaid(spec)`` takes a
``FlowSpec`` or a ``RouterSpec`` and returns a ``flowchart`` text that GitHub, MkDocs and most
editors render. The output is deterministic, so a diagram kept in a document changes only when the
file changes. No Mermaid library is used.

A flow: a step is a box (with what it runs, and its ``foreach`` and ``max_visits`` when set), a
``choice`` a diamond whose edges carry the ``when`` text and ``else``, a ``parallel`` block a
subgraph with its branches and the ``join`` rule, ``next`` a solid arrow, ``on_error`` and
``on_timeout`` dotted arrows, and ``end`` a terminal circle. A router: each route is a box with its
strategy and targets, and each fallback a dotted arrow, in order.

Example:
    >>> from skye.base.dsl import build
    >>> doc = build('flow "f" { step "a" { run = registry.x, next = end } }')
    >>> print(to_mermaid(doc.flows[0]))  # doctest: +NORMALIZE_WHITESPACE
    flowchart TD
      %% flow "f"
      start(("start")) --> n1
      n1["a<br/>run: registry.x"]
      n1 --> done
      done(("end"))
"""

from __future__ import annotations

from typing import Any, Literal

from skye.base.dsl.specs import ChoiceSpec, FlowSpec, ParallelSpec, RouterSpec, StepSpec, TargetSpec

Direction = Literal["TD", "LR"]
_ENTITIES = {"&": "#amp;", '"': "#quot;", "<": "#lt;", ">": "#gt;"}


def _escape(text: Any) -> str:
    """A label that Mermaid reads literally inside quotes."""
    out = str(text)
    for char, entity in _ENTITIES.items():
        out = out.replace(char, entity)
    return out.replace("\n", " ")


def _when_text(value: Any) -> str:
    text = getattr(value, "text", value)
    return str(text)


def _target_text(target: TargetSpec) -> str:
    return f"{target.provider}/{target.model}" if target.provider else target.model


def to_mermaid(spec: FlowSpec | RouterSpec, *, direction: Direction | None = None) -> str:
    """The Mermaid ``flowchart`` of a flow or a router.

    Args:
        spec: The ``FlowSpec`` or ``RouterSpec`` to draw (``build(text).flows`` or ``.routers``).
        direction: ``"TD"`` (top down, the default for a flow) or ``"LR"`` (left to right, the
            default for a router).

    Returns:
        The diagram text, ending with a newline; wrap it in a fenced code block marked ``mermaid``
        to show it in Markdown.

    Raises:
        TypeError: If ``spec`` is neither a flow nor a router (a prompt is a template, not a graph).
    """
    if isinstance(spec, FlowSpec):
        return _flow(spec, direction or "TD")
    if isinstance(spec, RouterSpec):
        return _router(spec, direction or "LR")
    raise TypeError(
        f"to_mermaid draws a flow or a router, not {type(spec).__name__}"
        " (a prompt is a template, not a graph)"
    )


def _flow(spec: FlowSpec, direction: Direction) -> str:
    ids: dict[str, str] = {}
    counter = 0

    def node_id(name: str) -> str:
        nonlocal counter
        if name not in ids:
            counter += 1
            ids[name] = f"n{counter}"
        return ids[name]

    # Number the nodes in file order first, so the identifiers do not depend on the edges.
    for node in spec.nodes:
        node_id(node.name)
        if isinstance(node, ParallelSpec):
            for branch in node.steps:
                node_id(f"{node.name}/{branch.name}")

    lines = [f"flowchart {direction}", f'  %% flow "{_escape(spec.name)}"']
    uses_end = False

    def target(name: str | None) -> str | None:
        nonlocal uses_end
        if name is None:
            return None
        if name == "end":
            uses_end = True
            return "done"
        return ids.get(name) or node_id(name)

    if spec.start is not None:
        lines.append(f'  start(("start")) --> {ids[spec.start]}')
    for node in spec.nodes:
        here = ids[node.name]
        if isinstance(node, StepSpec):
            lines.append(f'  {here}["{_step_label(node)}"]')
            _edges(lines, here, node.next, node.on_error, node.on_timeout, target)
        elif isinstance(node, ChoiceSpec):
            lines.append(f'  {here}{{"{_escape(node.name)}"}}')
            for option in node.branches:
                dest = target(option.next)
                if dest:
                    lines.append(f'  {here} -->|"{_escape(_when_text(option.when))}"| {dest}')
            if node.otherwise is not None:
                dest = target(node.otherwise.next)
                if dest:
                    lines.append(f'  {here} -->|"else"| {dest}')
        elif isinstance(node, ParallelSpec):
            title = f"{node.name} (join {node.join}, on branch error {node.on_branch_error})"
            lines.append(f'  subgraph {here} ["{_escape(title)}"]')
            lines.append("    direction TB")
            for branch in node.steps:
                lines.append(f'    {ids[f"{node.name}/{branch.name}"]}["{_step_label(branch)}"]')
            lines.append("  end")
            _edges(lines, here, node.next, node.on_error, None, target)
    if uses_end:
        lines.append('  done(("end"))')
    return "\n".join(lines) + "\n"


def _step_label(step: StepSpec) -> str:
    parts = [_escape(step.name)]
    if step.run:
        parts.append(f"run: {_escape(step.run)}")
    if step.foreach is not None:
        parts.append(f"foreach: {_escape(_when_text(step.foreach))}")
    if step.max_visits is not None:
        parts.append(f"max_visits: {step.max_visits}")
    return "<br/>".join(parts)


def _edges(
    lines: list[str],
    here: str,
    next_name: str | None,
    on_error: str | None,
    on_timeout: str | None,
    target: Any,
) -> None:
    dest = target(next_name)
    if dest:
        lines.append(f"  {here} --> {dest}")
    dest = target(on_error)
    if dest:
        lines.append(f'  {here} -.->|"on_error"| {dest}')
    dest = target(on_timeout)
    if dest:
        lines.append(f'  {here} -.->|"on_timeout"| {dest}')


def _router(spec: RouterSpec, direction: Direction) -> str:
    title = spec.name or "router"
    lines = [f"flowchart {direction}", f'  %% router "{_escape(title)}"']
    ids = {route.alias: f"r{index}" for index, route in enumerate(spec.routes, start=1)}
    extra = 0
    for route in spec.routes:
        here = ids[route.alias]
        label = [f"route {_escape(route.alias)}"]
        strategy = route.strategy or spec.strategy
        if strategy:
            label.append(f"strategy: {_escape(strategy)}")
        label.extend(_escape(_target_text(t)) for t in route.targets)
        lines.append(f'  {here}["{"<br/>".join(label)}"]')
        for order, name in enumerate(route.fallback, start=1):
            dest = ids.get(name)
            if dest is None:
                extra += 1
                dest = f"x{extra}"
                lines.append(f'  {dest}["route {_escape(name)}"]')
            lines.append(f'  {here} -.->|"fallback {order}"| {dest}')
        for order, fallback_target in enumerate(
            route.fallback_targets, start=len(route.fallback) + 1
        ):
            extra += 1
            dest = f"x{extra}"
            lines.append(f'  {dest}["{_escape(_target_text(fallback_target))}"]')
            lines.append(f'  {here} -.->|"fallback {order}"| {dest}')
    return "\n".join(lines) + "\n"


__all__ = ["to_mermaid"]
