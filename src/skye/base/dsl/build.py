"""Build the block models from the syntax tree, and apply the load-time checks of Requirement 54.4.

Nothing here reads a file or runs anything. Every mistake found is collected as a
:class:`~skye.base.dsl.errors.Diagnostic`; the models are built for the blocks that are sound.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from skye.base.dsl.errors import (
    DEFAULT_FILENAME,
    TOO_DEEP_FIX,
    Diagnostic,
    SkyeSyntaxError,
    did_you_mean,
    too_deep_reason,
)
from skye.base.dsl.expressions import Expression, check_expression, locate, references
from skye.base.dsl.parser import TYPE_NAMES, parse_collect
from skye.base.dsl.shapes import conform
from skye.base.dsl.specs import (
    DURATION,
    OUTPUT_FORMATS,
    STRATEGIES,
    AllowedFailsPolicySpec,
    BranchSpec,
    ChoiceSpec,
    ContextFieldSpec,
    ContextSpec,
    FlowSpec,
    OutputFieldSpec,
    OutputSpec,
    ParallelSpec,
    PromptPartSpec,
    PromptSpec,
    RetryPolicySpec,
    RetrySpec,
    RouterSpec,
    RouteSpec,
    SetSpec,
    StepSpec,
    TargetSpec,
    VariableSpec,
)
from skye.base.dsl.tree import (
    Attribute,
    Block,
    Bool,
    Expr,
    ListNode,
    MapEntry,
    MapNode,
    Name,
    Node,
    Num,
    Str,
    Tree,
    TypeCall,
    Value,
)
from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.plugins import get_registrar

#: The value of ``next`` that finishes a flow.
END = "end"

#: The prefixes of a reference (decision D66).
PREFIXES = ("registry", "flow", "router", "prompt", "step", "context", "env", "item")

_WAIT_MESSAGE = '"{}" needs persistence and is not available in this version'
_V2_MESSAGE = '"{}" is not available in this version'
_V2_FLOW = frozenset({"wait", "on_event"})
_V2_PROMPT = frozenset({"examples", "content", "from", "bind", "parts", "separator", "include"})
#: The word of an ``output`` block that names a map variable giving the fields at render time.
_SCHEMA_WORD = "schema"
_SCALARS = ("string", "number", "bool")
_ROLES = ("system", "user", "assistant")
_STEP_FIELDS = (
    "run",
    "input",
    "next",
    "on_error",
    "on_timeout",
    "timeout",
    "retry",
    "max_visits",
    "foreach",
)
_BRANCH_FIELDS = ("run", "input", "timeout", "retry", "foreach")
_TARGET_FIELDS = (
    "model",
    "provider",
    "api_key",
    "api_base",
    "api_version",
    "region",
    "timeout",
    "max_retries",
    "weight",
    "tpm",
    "rpm",
    "cost_per_1k_prompt_tokens",
    "cost_per_1k_completion_tokens",
    "tags",
    "metadata",
    "options",
)
_TYPE_WORDS = {
    "string": "a string",
    "number": "a number",
    "bool": "a bool",
    "list": "a list",
    "map": "a map",
}
_PROMPT_LITERALS = frozenset({"true", "false", "none", "True", "False", "None"})


@dataclass(kw_only=True)
class Document:
    """The result of :func:`build`: the validated blocks of a file and the mistakes found.

    Attributes:
        filename: The file name used in diagnostics.
        routers: The ``router`` blocks that are sound.
        flows: The ``flow`` blocks that are sound.
        prompts: The ``prompt`` blocks that are sound.
        diagnostics: Every mistake found, sorted by position (empty if the file is valid).
        metadata: The front matter of the file (``---`` ... ``---`` at the top, TOML); empty
            without.
    """

    filename: str
    routers: list[RouterSpec] = field(default_factory=list)
    flows: list[FlowSpec] = field(default_factory=list)
    prompts: list[PromptSpec] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when the file has no mistake."""
        return not self.diagnostics

    def raise_for_errors(self) -> Document:
        """Raise :class:`SkyeSyntaxError` with every diagnostic if there is any;
        else return self.
        """
        if self.diagnostics:
            raise SkyeSyntaxError(self.diagnostics)
        return self

    def _pick(self, items: list[Any], kind: str, name: str | None) -> Any:
        if name is None:
            if len(items) == 1:
                return items[0]
            raise KeyError(
                f"the file has {len(items)} {kind} blocks; give the name of one"
                if items
                else f"the file has no {kind} block"
            )
        for item in items:
            if item.name == name:
                return item
        known = ", ".join(i.name or "(unnamed)" for i in items) or "none"
        raise KeyError(f'no {kind} "{name}" in the file. Defined: {known}')

    def router(self, name: str | None = None) -> RouterSpec:
        """The router called ``name`` (or the only one). Raises ``KeyError`` if there is none."""
        found: RouterSpec = self._pick(self.routers, "router", name)
        return found

    def flow(self, name: str | None = None) -> FlowSpec:
        """The flow called ``name`` (or the only one). Raises ``KeyError`` if there is none."""
        found: FlowSpec = self._pick(self.flows, "flow", name)
        return found

    def prompt(self, name: str | None = None) -> PromptSpec:
        """The prompt called ``name`` (or the only one). Raises ``KeyError`` if there is none."""
        found: PromptSpec = self._pick(self.prompts, "prompt", name)
        return found


class _SkipError(Exception):
    """The item is wrong and has been reported; build the rest."""


@dataclass(kw_only=True)
class _FlowCtx:
    name: str
    declared: dict[str, str]
    steps: list[str]
    nodes: list[str]
    where: str = ""
    item_ok: bool = False

    def derive(self, *, where: str, item_ok: bool = False) -> _FlowCtx:
        return _FlowCtx(
            name=self.name,
            declared=self.declared,
            steps=self.steps,
            nodes=self.nodes,
            where=where,
            item_ok=item_ok,
        )


class _Builder:
    def __init__(self, tree: Tree, registry_names: Collection[str] | None) -> None:
        self.tree = tree
        self.file = tree.filename
        self.registry: set[str] | None = set(registry_names) if registry_names is not None else None
        self.errors: list[Diagnostic] = []
        self.flow_names = self.labels("flow")
        self.router_names = self.labels("router")
        self.prompt_names = self.labels("prompt")
        self.flow_calls: dict[str, list[str]] = {}
        self.flow_blocks: dict[str, Block] = {}
        # the prompt being built: its variables and its output blocks inside when blocks
        self.prompt_variables: list[VariableSpec] = []
        self.conditional_outputs: list[Block] = []

    def labels(self, kind: str) -> list[str]:
        return [b.label_text for b in self.tree.blocks if b.kind == kind and b.label_text]

    # -- reporting -----------------------------------------------------------------------------
    def err(self, line: int, column: int, reason: str, fix: str = "") -> None:
        self.errors.append(
            Diagnostic(file=self.file, line=line, column=column, reason=reason, fix=fix)
        )

    def at(self, node: Node, reason: str, fix: str = "") -> None:
        self.err(node.line, node.column, reason, fix)

    def fail(self, node: Node, reason: str, fix: str = "") -> _SkipError:
        self.at(node, reason, fix)
        return _SkipError()

    # -- document ------------------------------------------------------------------------------
    def build(self) -> Document:
        doc = Document(filename=self.file, metadata=dict(self.tree.metadata))
        seen: set[tuple[str, str]] = set()
        for block in self.tree.blocks:
            name = block.label_text
            if block.kind in ("router", "flow", "prompt") and name is not None:
                if (block.kind, name) in seen:
                    self.at(block, f'{block.kind} "{name}" is defined twice')
                seen.add((block.kind, name))
            try:
                if block.kind == "router":
                    doc.routers.append(self.router(block))
                elif block.kind == "flow":
                    doc.flows.append(self.flow(block))
                elif block.kind == "prompt":
                    doc.prompts.append(self.prompt(block))
                elif block.kind in _V2_PROMPT:
                    self.at(
                        block,
                        _V2_MESSAGE.format(block.kind),
                        "In version 1 each file is self-sufficient; load several files from "
                        "Python.",
                    )
                else:
                    self.at(
                        block,
                        f'unknown block "{block.kind}".',
                        did_you_mean(block.kind, ["router", "flow", "prompt"])
                        or "Use router, flow or prompt.",
                    )
            except _SkipError:
                pass
        self.check_flow_cycles()
        doc.diagnostics = sorted(self.errors, key=lambda d: (d.line, d.column))
        return doc

    # -- generic body reading ------------------------------------------------------------------
    def split(
        self,
        block: Block,
        what: str,
        attrs: Collection[str],
        blocks: Collection[str] = (),
        *,
        v2: Collection[str] = (),
        unavailable: dict[str, str] | None = None,
        v2_message: str = _WAIT_MESSAGE,
    ) -> tuple[dict[str, Attribute], list[Attribute], list[Attribute], list[Block]]:
        """Sort a body into attributes, ``set`` and ``emit`` statements and blocks; report the
        unknown.
        """
        found: dict[str, Attribute] = {}
        sets: list[Attribute] = []
        emits: list[Attribute] = []
        subs: list[Block] = []
        known_all = list(attrs) + list(blocks)
        for item in block.body:
            if isinstance(item, Block):
                if item.kind in blocks:
                    subs.append(item)
                elif item.kind in v2:
                    self.at(item, v2_message.format(item.kind))
                else:
                    self.unknown(item, item.kind, what, known_all)
                continue
            if item.keyword == "set":
                sets.append(item)
            elif item.keyword == "emit":
                emits.append(item)
            elif item.name in v2:
                self.err(item.name_line, item.name_column, v2_message.format(item.name))
            elif unavailable and item.name in unavailable:
                self.err(item.name_line, item.name_column, unavailable[item.name])
            elif item.name in attrs:
                if item.name in found:
                    self.err(
                        item.name_line, item.name_column, f'"{item.name}" is set twice in {what}'
                    )
                found[item.name] = item
            else:
                self.unknown(item, item.name, what, known_all)
        return found, sets, emits, subs

    def unknown(self, node: Node, word: str, what: str, known: Collection[str]) -> None:
        line = (node.name_line if isinstance(node, Attribute) else 0) or node.line
        col = (node.name_column if isinstance(node, Attribute) else 0) or node.column
        if word.endswith("_seconds") and word[: -len("_seconds")] in known:
            new = word[: -len("_seconds")]
            self.err(line, col, f'"{word}" was renamed "{new}" and takes a duration such as "60s"')
            return
        self.err(
            line,
            col,
            f'unknown field "{word}" in {what}.',
            did_you_mean(word, known) or "Known fields: " + ", ".join(known) + ".",
        )

    # -- typed readers -------------------------------------------------------------------------
    def read_bool(self, attr: Attribute) -> bool:
        if isinstance(attr.value, Bool):
            return attr.value.value
        raise self.fail(attr.value, f'"{attr.name}" must be true or false')

    def read_int(self, attr: Attribute, minimum: int = 0) -> int:
        value = attr.value
        if isinstance(value, Num) and isinstance(value.value, int) and value.value >= minimum:
            return value.value
        raise self.fail(value, f'"{attr.name}" must be a whole number of at least {minimum}')

    def read_str(self, attr: Attribute) -> str:
        if isinstance(attr.value, Str):
            return attr.value.value
        raise self.fail(attr.value, f'"{attr.name}" must be a string in quotes')

    def read_duration(self, name: str, value: Value) -> str:
        if isinstance(value, Str) and DURATION.match(value.value.strip()):
            return value.value.strip()
        if isinstance(value, Str | Num):
            raw = value.raw
        elif isinstance(value, Name):
            raw = value.text
        elif isinstance(value, Expr):
            raw = value.text
        else:
            raw = type(value).__name__
        raise self.fail(value, f"{name} = {raw} is not a duration.", 'Use "30s", "5m" or "24h"')

    def read_strategy(self, attr: Attribute) -> str:
        """A built-in strategy, or a name that a plugin registered (asked of the registrar only when the name is not a built-in)."""
        text = self.read_str(attr)
        if text in STRATEGIES:
            return text
        registered = get_registrar()
        try:
            registered.get("routing_strategy", text)
        except ConfigurationError:
            names = [*STRATEGIES, *(n for n in registered.names("routing_strategy") if n not in STRATEGIES)]
            raise self.fail(
                attr.value,
                f'strategy "{text}" is not valid.',
                did_you_mean(text, names) or "Use one of: " + ", ".join(names) + ".",
            ) from None
        return text

    # -- values --------------------------------------------------------------------------------
    def literal(self, node: Value, *, env_text: bool = False) -> Any:
        """A tree value as plain data; references and expressions become :class:`Expression`."""
        if isinstance(node, Str | Num | Bool):
            return node.value
        if isinstance(node, ListNode):
            return [self.literal(item, env_text=env_text) for item in node.items]
        if isinstance(node, MapNode):
            return {e.key: self.literal(e.value, env_text=env_text) for e in node.entries}
        if isinstance(node, Name):
            if env_text:
                if len(node.path) == 2 and node.path[0] == "env":
                    return "${" + node.path[1] + "}"
                raise self.fail(
                    node, f'"{node.text}" is not allowed here.', "Use a literal value or env.NAME."
                )
            return Expression(text=node.text, line=node.line, column=node.column)
        if isinstance(node, Expr):
            if env_text:
                raise self.fail(
                    node, "an expression is not allowed here.", "Use a literal value or env.NAME."
                )
            return Expression(text=node.text, line=node.line, column=node.column)
        raise self.fail(node, f'"{node.name}(...)" is not allowed here')

    def make(
        self, cls: Any, where: Node, kwargs: dict[str, Any], nodes: dict[str, Node] | None = None
    ) -> Any:
        """Build a model; a value the model refuses is reported at its own position."""
        try:
            return cls(**kwargs)
        except ValidationError as exc:
            name = str(exc.details.get("field", ""))
            node = (nodes or {}).get(name, where)
            raise self.fail(node, f'"{name}": {str(exc.message).split(": ", 1)[-1]}') from None

    # -- router --------------------------------------------------------------------------------
    def router(self, block: Block) -> RouterSpec:
        if block.label is not None and not isinstance(block.label, Str):
            self.at(block.label, 'the name of a router is a string: router "main" { ... }')
        what = f'router "{block.label_text}"' if block.label_text else "router"
        attrs, _, _, subs = self.split(
            block,
            what,
            ("strategy", "cooldown", "enable_pre_call_checks"),
            ("route", "retry_policy", "allowed_fails_policy"),
        )
        kwargs: dict[str, Any] = {"name": block.label_text}
        for name, attr in attrs.items():
            try:
                if name == "strategy":
                    kwargs[name] = self.read_strategy(attr)
                elif name == "cooldown":
                    kwargs[name] = self.read_duration(name, attr.value)
                else:
                    kwargs[name] = self.read_bool(attr)
            except _SkipError:
                pass
        routes: list[RouteSpec] = []
        retry: list[RetryPolicySpec] = []
        fails: list[AllowedFailsPolicySpec] = []
        for sub in subs:
            try:
                if sub.kind == "route":
                    routes.append(self.route(sub))
                elif sub.kind == "retry_policy":
                    retry.append(self.retry_policy(sub))
                else:
                    fails.append(self.fails_policy(sub))
            except _SkipError:
                pass
        aliases = [r.alias for r in routes]
        for dup in sorted({a for a in aliases if aliases.count(a) > 1}):
            self.at(block, f'route "{dup}" is defined twice')
        self.check_fallbacks(subs, aliases)
        kwargs.update(routes=routes, retry_policies=retry, allowed_fails_policies=fails)
        return self.make(RouterSpec, block, kwargs)  # type: ignore[no-any-return]

    def check_fallbacks(self, subs: list[Block], aliases: list[str]) -> None:
        for sub in subs:
            if sub.kind != "route":
                continue
            for item in sub.body:
                if (
                    isinstance(item, Attribute)
                    and item.name == "fallback"
                    and isinstance(item.value, ListNode)
                ):
                    for entry in item.value.items:
                        if isinstance(entry, Str) and entry.value not in aliases:
                            self.at(
                                entry,
                                f'route "{sub.label_text}" has no route "{entry.value}" in '
                                f"fallback.",
                                did_you_mean(entry.value, aliases)
                                or "Defined routes: " + ", ".join(aliases) + ".",
                            )

    def route(self, block: Block) -> RouteSpec:
        if not isinstance(block.label, Str):
            raise self.fail(block, 'a route needs a name: route "fast" { ... }')
        alias = block.label.value
        if block.value is not None:
            return self.shorthand_route(block, alias)
        what = f'route "{alias}"'
        attrs, _, _, subs = self.split(
            block, what, ("strategy", "fallback_on_error", "fallback"), ("target",)
        )
        kwargs: dict[str, Any] = {"alias": alias}
        for name, attr in attrs.items():
            try:
                if name == "strategy":
                    kwargs[name] = self.read_strategy(attr)
                elif name == "fallback_on_error":
                    kwargs[name] = self.read_bool(attr)
                else:
                    value = attr.value
                    if not isinstance(value, ListNode) or not all(
                        isinstance(i, Str) for i in value.items
                    ):
                        raise self.fail(
                            attr.value, '"fallback" must be a list of route names: ["a", "b"]'
                        )
                    kwargs[name] = [i.value for i in value.items if isinstance(i, Str)]
            except _SkipError:
                pass
        targets: list[TargetSpec] = []
        for sub in subs:
            try:
                items: list[tuple[str, Value, Node]] = []
                for item in sub.body:
                    if isinstance(item, Attribute) and not item.keyword:
                        items.append((item.name, item.value, item))
                    else:
                        word = item.name if isinstance(item, Attribute) else item.kind
                        self.unknown(item, word, "target", _TARGET_FIELDS)
                targets.append(self.target(items, sub, f"{what} target"))
            except _SkipError:
                pass
        if not subs:
            self.at(
                block,
                f'route "{alias}" has no target.',
                'Add: target { model = "...", provider = "..." }',
            )
        kwargs["targets"] = targets
        return self.make(RouteSpec, block, kwargs)  # type: ignore[no-any-return]

    def shorthand_route(self, block: Block, alias: str) -> RouteSpec:
        value = block.value
        if not isinstance(value, ListNode) or not value.items:
            raise self.fail(
                value or block,
                f'route "{alias}" needs a list of models: route "{alias}" = ["provider/model", '
                f"...]",
            )
        targets: list[TargetSpec] = []
        for entry in value.items:
            try:
                if isinstance(entry, Str):
                    provider, sep, model = entry.value.partition("/")
                    if not sep or not provider or not model:
                        raise self.fail(entry, f'"{entry.value}" is not of the form provider/model')
                    targets.append(
                        self.make(TargetSpec, entry, {"provider": provider, "model": model})
                    )
                elif isinstance(entry, MapNode):
                    items = [(e.key, e.value, e) for e in entry.entries]
                    targets.append(
                        self.target(items, entry, f'route "{alias}" entry', split_model=True)
                    )
                else:
                    raise self.fail(
                        entry, 'an entry is "provider/model" or { model = "provider/model", ... }'
                    )
            except _SkipError:
                pass
        if not targets:
            raise _SkipError()
        return self.make(  # type: ignore[no-any-return]
            RouteSpec,
            block,
            {"alias": alias, "targets": targets[:1], "fallback_targets": targets[1:]},
        )

    def target(
        self,
        items: Sequence[tuple[str, Value, Node]],
        where: Node,
        what: str,
        *,
        split_model: bool = False,
    ) -> TargetSpec:
        kwargs: dict[str, Any] = {}
        nodes: dict[str, Node] = {}
        for key, value, node in items:
            line = (node.name_line if isinstance(node, Attribute) else 0) or node.line
            col = (node.name_column if isinstance(node, Attribute) else 0) or node.column
            if key not in _TARGET_FIELDS:
                self.unknown(node, key, what, _TARGET_FIELDS)
                continue
            if key in kwargs:
                self.err(line, col, f'"{key}" is set twice in {what}')
                continue
            try:
                if key == "timeout":
                    kwargs[key] = self.read_duration(key, value)
                else:
                    kwargs[key] = self.literal(value, env_text=True)
            except _SkipError:
                continue
            nodes[key] = value
        if split_model and "model" in kwargs and "provider" not in kwargs:
            provider, sep, model = str(kwargs["model"]).partition("/")
            if not sep or not provider or not model:
                raise self.fail(
                    nodes["model"], f'"{kwargs["model"]}" is not of the form provider/model'
                )
            kwargs.update(provider=provider, model=model)
        return self.make(TargetSpec, where, kwargs, nodes)  # type: ignore[no-any-return]

    def retry_policy(self, block: Block) -> RetryPolicySpec:
        if not isinstance(block.label, Str):
            raise self.fail(
                block, 'a retry_policy needs an error type: retry_policy "RateLimitError" { ... }'
            )
        what = f'retry_policy "{block.label.value}"'
        attrs, _, _, _ = self.split(
            block, what, ("max_retries", "retry_after", "exponential_backoff")
        )
        kwargs: dict[str, Any] = {"error_type": block.label.value}
        for name, attr in attrs.items():
            try:
                if name == "max_retries":
                    kwargs[name] = self.read_int(attr)
                elif name == "retry_after":
                    kwargs[name] = self.read_duration(name, attr.value)
                else:
                    kwargs[name] = self.read_bool(attr)
            except _SkipError:
                pass
        return self.make(RetryPolicySpec, block, kwargs)  # type: ignore[no-any-return]

    def fails_policy(self, block: Block) -> AllowedFailsPolicySpec:
        if not isinstance(block.label, Str):
            raise self.fail(
                block,
                "an allowed_fails_policy needs an error type: "
                'allowed_fails_policy "RateLimitError" { ... }',
            )
        what = f'allowed_fails_policy "{block.label.value}"'
        attrs, _, _, _ = self.split(block, what, ("allowed_fails_per_minute",))
        if "allowed_fails_per_minute" not in attrs:
            raise self.fail(
                block,
                f"{what} has no allowed_fails_per_minute.",
                "Add: allowed_fails_per_minute = 100",
            )
        return self.make(  # type: ignore[no-any-return]
            AllowedFailsPolicySpec,
            block,
            {
                "error_type": block.label.value,
                "allowed_fails_per_minute": self.read_int(attrs["allowed_fails_per_minute"]),
            },
        )

    # -- expressions and references ------------------------------------------------------------
    def expr(self, node: Value, ctx: _FlowCtx) -> None:
        """Check an expression or a reference of a flow: syntax, allowed names, declared fields."""
        if isinstance(node, Name):
            self.chain(node.path, node.line, node.column, ctx)
        elif isinstance(node, Expr):
            problems = check_expression(
                node.text, filename=self.file, line=node.line, column=node.column
            )
            if problems:
                self.errors.extend(problems)
                return
            for chain, ref in references(node.text):
                line, col = locate(node.text, ref, node.line, node.column)
                self.chain(chain, line, col, ctx)

    def scan(self, node: Value, ctx: _FlowCtx) -> None:
        """Check every reference and expression inside a value."""
        if isinstance(node, Name | Expr):
            self.expr(node, ctx)
        elif isinstance(node, ListNode):
            for item in node.items:
                self.scan(item, ctx)
        elif isinstance(node, MapNode):
            for entry in node.entries:
                self.scan(entry.value, ctx)
        elif isinstance(node, TypeCall):
            self.at(node, f'"{node.name}(...)" is not allowed here')

    def chain(self, chain: tuple[str, ...], line: int, col: int, ctx: _FlowCtx) -> None:
        root = chain[0]
        text = ".".join(chain)
        prefix = f"{ctx.where}: " if ctx.where else ""
        if root == "context":
            if len(chain) < 2:
                self.err(line, col, '"context" needs a field: context.NAME')
            elif chain[1] not in ctx.declared:
                names = list(ctx.declared)
                self.err(
                    line,
                    col,
                    f'"context.{chain[1]}" is not declared.',
                    (
                        f"Declared: {', '.join(names) or '(none)'}. "
                        f"{did_you_mean(chain[1], names)}"
                    ).strip(),
                )
        elif root == "step":
            if len(chain) < 2:
                self.err(line, col, '"step" needs a step name: step.NAME.output')
            elif chain[1] not in ctx.steps:
                self.err(
                    line,
                    col,
                    f'"step.{chain[1]}" is not a step of this flow.',
                    (
                        f"Defined steps: {', '.join(ctx.steps)}. "
                        f"{did_you_mean(chain[1], ctx.steps)}"
                    ).strip(),
                )
            elif len(chain) < 3 or chain[2] != "output":
                self.err(line, col, f'"{text}" is not a result.', f"Use step.{chain[1]}.output")
        elif root == "env":
            if len(chain) != 2:
                self.err(line, col, f'"{text}" is not an environment variable.', "Use env.NAME")
        elif root == "item":
            if not ctx.item_ok:
                self.err(line, col, '"item" can only be used in a step with foreach')
        elif root == "registry":
            if len(chain) < 2:
                self.err(line, col, '"registry" needs a name: registry.NAME')
            elif self.registry is not None and chain[1] not in self.registry:
                known = sorted(self.registry)
                self.err(
                    line,
                    col,
                    f'{prefix}"{chain[1]}" is not in the registry.',
                    (
                        f"Known: {', '.join(known) or '(none)'}. "
                        f"{did_you_mean(chain[1], known)}"
                    ).strip(),
                )
        elif root in ("flow", "router", "prompt"):
            known = {
                "flow": self.flow_names,
                "router": self.router_names,
                "prompt": self.prompt_names,
            }[root]
            if len(chain) < 2:
                self.err(line, col, f'"{root}" needs a name: {root}.NAME')
            elif chain[1] not in known:
                self.err(
                    line,
                    col,
                    f'{prefix}{root} "{chain[1]}" is not defined in this file.',
                    (
                        f"Defined: {', '.join(known) or '(none)'}. "
                        f"{did_you_mean(chain[1], known)}"
                    ).strip(),
                )
        elif len(chain) == 1:
            self.err(
                line,
                col,
                f'"{root}" has no prefix.',
                f"Use context.{root}, step.{root}.output or item.",
            )
        else:
            self.err(
                line,
                col,
                f'unknown prefix "{root}" in "{text}".',
                "Known prefixes: " + ", ".join(PREFIXES) + ".",
            )

    # -- flow ----------------------------------------------------------------------------------
    def flow(self, block: Block) -> FlowSpec:
        if not isinstance(block.label, Str):
            raise self.fail(block, 'a flow needs a name: flow "name" { ... }')
        name = block.label.value
        what = f'flow "{name}"'
        self.flow_blocks[name] = block
        _, _, _, subs = self.split(
            block, what, (), ("context", "step", "parallel", "choice"), v2=_V2_FLOW
        )
        context = ContextSpec()
        declared: dict[str, str] = {}
        ctx_blocks = [s for s in subs if s.kind == "context"]
        if len(ctx_blocks) > 1:
            self.at(ctx_blocks[1], f"{what} has more than one context block")
        if ctx_blocks:
            context = self.context(ctx_blocks[0])
            declared = {f.name: f.type for f in context.fields}
        nodes_blocks = [s for s in subs if s.kind != "context"]
        top: list[str] = []
        steps: list[str] = []
        for node in nodes_blocks:
            label = node.label_text if isinstance(node.label, Str) else None
            if label is None:
                self.at(node, f'a {node.kind} needs a name: {node.kind} "Name" {{ ... }}')
                continue
            if label == END:
                self.at(node.label or node, f'"{END}" is reserved: it finishes the flow')
            if label in steps:
                self.at(node.label or node, f'{node.kind} "{label}" is defined twice')
                continue
            top.append(label)
            steps.append(label)
            if node.kind == "parallel":
                for child in node.blocks():
                    if child.kind == "step" and isinstance(child.label, Str):
                        if child.label.value in steps:
                            self.at(child.label, f'step "{child.label.value}" is defined twice')
                        else:
                            steps.append(child.label.value)
        ctx = _FlowCtx(name=name, declared=declared, steps=steps, nodes=top)
        built: list[Any] = []
        calls: list[str] = []
        for node in nodes_blocks:
            if not isinstance(node.label, Str):
                continue
            try:
                if node.kind == "step":
                    built.append(self.step(node, ctx, branch=False, calls=calls))
                elif node.kind == "parallel":
                    built.append(self.parallel(node, ctx, calls))
                else:
                    built.append(self.choice(node, ctx))
            except _SkipError:
                pass
        self.flow_calls[name] = calls
        self.check_graph(built, v2=any(_uses_v2(n) for n in nodes_blocks))
        return self.make(  # type: ignore[no-any-return]
            FlowSpec, block, {"name": name, "context": context, "nodes": built}
        )

    def context(self, block: Block) -> ContextSpec:
        fields: list[ContextFieldSpec] = []
        for item in block.body:
            if not isinstance(item, Attribute) or item.keyword:
                continue
            try:
                kind, default = self.typed(item.value, f'"{item.name}"', "default")
                fields.append(
                    ContextFieldSpec(
                        name=item.name,
                        type=kind,  # type: ignore[arg-type]
                        default=default,
                        required=default is None,
                    )
                )
            except _SkipError:
                pass
        names = [f.name for f in fields]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            self.at(block, f'context field "{dup}" is declared twice')
        return ContextSpec(fields=fields)

    def typed(self, value: Value, label: str, word: str) -> tuple[str, Any]:
        """The type and default of ``string("x")``, ``number(0)`` or a bare ``list``."""
        default: Any = None
        if isinstance(value, TypeCall):
            kind = value.name
            if value.second is not None:
                raise self.fail(
                    value.second,
                    f"{label}: {kind}(...) takes one argument here.",
                    "Only list({ ... }, []) and map({ ... }, {}) in a prompt take a default "
                    "after the shape.",
                )
            if value.default is not None:
                default = self.literal(value.default)
                found = self.infer(value.default)
                if found is not None and found != kind:
                    raise self.fail(
                        value.default, f"{label} is {kind}, the {word} is {_TYPE_WORDS[found]}"
                    )
        elif isinstance(value, Name) and len(value.path) == 1 and value.path[0] in TYPE_NAMES:
            kind = value.path[0]
        elif isinstance(value, Name) and value.path == ("image",):
            raise self.fail(value, '"image" is not available in this version')
        else:
            raise self.fail(
                value,
                f"{label} needs a type.",
                "Use string, number, bool, list or map, for example number(0).",
            )
        return kind, default

    def infer(self, node: Value) -> str | None:
        """The type of a value when it can be known without running the flow."""
        if isinstance(node, Str):
            return "string"
        if isinstance(node, Bool):
            return "bool"
        if isinstance(node, Num):
            return "number"
        if isinstance(node, ListNode):
            return "list"
        if isinstance(node, MapNode):
            return "map"
        if isinstance(node, Expr):
            try:
                return _infer_ast(ast.parse(node.text, mode="eval").body)
            except SyntaxError:
                return None
        return None

    def target_name(self, attr: Attribute, ctx: _FlowCtx) -> str | None:
        value = attr.value
        if isinstance(value, Name) and value.path == (END,):
            return END
        if isinstance(value, Str):
            if value.value in ctx.nodes:
                return value.value
            self.at(
                value,
                f'unknown step "{value.value}" in "{attr.name}".',
                (
                    f"Defined steps: {', '.join(ctx.nodes)}. "
                    f"{did_you_mean(value.value, ctx.nodes)}"
                ).strip(),
            )
            return None
        if isinstance(value, Name):
            self.at(
                value,
                f"{attr.name} = {value.text} needs quotes.",
                f'Write: {attr.name} = "{value.text}" or {attr.name} = end',
            )
        else:
            self.at(value, f'"{attr.name}" must be a step name in quotes or end')
        return None

    def sets(self, items: list[Attribute], ctx: _FlowCtx) -> list[SetSpec]:
        out: list[SetSpec] = []
        for item in items:
            self.scan(item.value, ctx)
            if item.name not in ctx.declared:
                names = list(ctx.declared)
                self.err(
                    item.name_line,
                    item.name_column,
                    f'"{item.name}" is not declared.',
                    (
                        f"Declared: {', '.join(names) or '(none)'}. "
                        f"{did_you_mean(item.name, names)}"
                    ).strip(),
                )
                continue
            declared = ctx.declared[item.name]
            found = self.infer(item.value)
            if found is not None and found != declared:
                self.err(
                    item.name_line,
                    item.name_column,
                    f'"{item.name}" is {declared}, the value is {_TYPE_WORDS[found]}',
                )
                continue
            try:
                out.append(SetSpec(name=item.name, value=self.literal(item.value)))
            except _SkipError:
                pass
        return out

    def emits(self, items: list[Attribute]) -> list[str]:
        out: list[str] = []
        for item in items:
            if isinstance(item.value, Str):
                out.append(item.value.value)
            else:
                self.at(item.value, 'emit needs the name of an event in quotes: emit "name"')
        return out

    def step(self, block: Block, ctx: _FlowCtx, *, branch: bool, calls: list[str]) -> StepSpec:
        label = block.label_text or ""
        what = f'step "{label}"'
        known = _BRANCH_FIELDS if branch else _STEP_FIELDS
        unavailable = (
            {
                w: f'"{w}" is not allowed in a step inside a parallel block; '
                f"set it on the parallel block"
                for w in ("next", "on_error", "on_timeout")
            }
            if branch
            else None
        )
        attrs, set_items, emit_items, _ = self.split(
            block, what, known, (), v2=_V2_FLOW, unavailable=unavailable
        )
        sub_ctx = ctx.derive(where=what, item_ok="foreach" in attrs)
        kwargs: dict[str, Any] = {"name": label}
        for name, attr in attrs.items():
            try:
                self.step_field(name, attr, kwargs, ctx, sub_ctx, calls)
            except _SkipError:
                pass
        kwargs["set"] = self.sets(set_items, sub_ctx)
        kwargs["emit"] = self.emits(emit_items)
        reserved = _uses_v2(block)  # a version 2 step is reported once, not for what it lacks
        if not (attrs.get("run") or set_items or emit_items or attrs.get("foreach") or reserved):
            self.at(
                block,
                f"{what} has nothing to do.",
                "Add: run = registry.NAME (or set, emit or foreach)",
            )
        if not branch and "next" not in attrs and not reserved:
            self.at(block, f"{what} has no next.", 'Add: next = "<step>" or next = end')
        spec: StepSpec = self.make(StepSpec, block, kwargs)
        spec.line, spec.column = block.line, block.column
        return spec

    def step_field(
        self,
        name: str,
        attr: Attribute,
        kwargs: dict[str, Any],
        ctx: _FlowCtx,
        sub_ctx: _FlowCtx,
        calls: list[str],
    ) -> None:
        value = attr.value
        if name == "run":
            self.run_ref(value, sub_ctx, calls)
            assert isinstance(value, Name)
            kwargs["run"] = value.text
        elif name == "input":
            if not isinstance(value, MapNode):
                raise self.fail(value, '"input" must be a map: input = { name = value }')
            self.scan(value, sub_ctx)
            kwargs["input"] = self.literal(value)
        elif name in ("next", "on_error", "on_timeout"):
            target = self.target_name(attr, ctx)
            if target is not None:
                kwargs[name] = target
        elif name == "timeout":
            kwargs[name] = self.read_duration(name, value)
        elif name == "retry":
            kwargs[name] = self.retry(value)
        elif name == "max_visits":
            kwargs[name] = self.read_int(attr, 1)
        elif name == "foreach":
            self.scan(value, ctx.derive(where=sub_ctx.where))
            kwargs[name] = self.literal(value)

    def run_ref(self, value: Value, ctx: _FlowCtx, calls: list[str]) -> None:
        if isinstance(value, Str) or (isinstance(value, Name) and len(value.path) == 1):
            text = value.value if isinstance(value, Str) else value.text
            raise self.fail(
                value,
                f'"{text}" has no prefix.',
                f"Use registry.{text}, flow.{text} or router.{text}",
            )
        if not isinstance(value, Name):
            raise self.fail(
                value, '"run" must be a reference: registry.NAME, flow.NAME or router.NAME'
            )
        if value.path[0] not in ("registry", "flow", "router"):
            raise self.fail(
                value,
                f'"{value.text}" cannot be run.',
                "Use registry.NAME, flow.NAME or router.NAME.",
            )
        self.chain(value.path, value.line, value.column, ctx)
        if value.path[0] == "flow":
            calls.append(value.path[1])

    def retry(self, value: Value) -> RetrySpec:
        if isinstance(value, Num) and isinstance(value.value, int) and value.value >= 0:
            return RetrySpec(max=value.value)
        if not isinstance(value, MapNode):
            raise self.fail(
                value,
                '"retry" is a number or a map: retry = 3 or retry = { max = 3, after = "2s" }',
            )
        kwargs: dict[str, Any] = {}
        for entry in value.entries:
            try:
                num = entry.value
                if entry.key == "max":
                    if not (isinstance(num, Num) and isinstance(num.value, int) and num.value >= 0):
                        raise self.fail(entry.value, '"max" must be a whole number')
                    kwargs["max"] = num.value
                elif entry.key == "after":
                    kwargs["after"] = self.read_duration("after", entry.value)
                elif entry.key == "backoff":
                    if not isinstance(num, Bool):
                        raise self.fail(entry.value, '"backoff" must be true or false')
                    kwargs["backoff"] = num.value
                else:
                    self.unknown(entry, entry.key, "retry", ("max", "after", "backoff"))
            except _SkipError:
                pass
        return RetrySpec(**kwargs)

    def parallel(self, block: Block, ctx: _FlowCtx, calls: list[str]) -> ParallelSpec:
        label = block.label_text or ""
        what = f'parallel "{label}"'
        attrs, set_items, emit_items, subs = self.split(
            block,
            what,
            ("join", "on_branch_error", "next", "on_error"),
            ("step",),
            v2=_V2_FLOW,
            unavailable={
                "timeout": '"timeout" is not available on a parallel block in this version; '
                "put timeout on each step"
            },
        )
        for stray in set_items + emit_items:
            self.at(
                stray, f'"{stray.keyword}" is not allowed in a parallel block; put it in a step'
            )
        kwargs: dict[str, Any] = {"name": label}
        for name, attr in attrs.items():
            try:
                if name in ("join", "on_branch_error"):
                    options = ("all", "any") if name == "join" else ("cancel", "continue")
                    text = self.read_str(attr)
                    if text not in options:
                        raise self.fail(
                            attr.value,
                            f'{name} "{text}" is not valid.',
                            f"Use {' or '.join(options)}",
                        )
                    kwargs[name] = text
                else:
                    target = self.target_name(attr, ctx)
                    if target is not None:
                        kwargs[name] = target
            except _SkipError:
                pass
        branches: list[StepSpec] = []
        for sub in subs:
            if not isinstance(sub.label, Str):
                self.at(sub, 'a step needs a name: step "Name" { ... }')
                continue
            try:
                branches.append(self.step(sub, ctx, branch=True, calls=calls))
            except _SkipError:
                pass
        if not subs:
            self.at(block, f"{what} has no steps.", 'Add: step "Name" { run = registry.NAME }')
        if "next" not in attrs:
            self.at(block, f"{what} has no next.", 'Add: next = "<step>" or next = end')
        kwargs["steps"] = branches
        spec: ParallelSpec = self.make(ParallelSpec, block, kwargs)
        spec.line, spec.column = block.line, block.column
        return spec

    def choice(self, block: Block, ctx: _FlowCtx) -> ChoiceSpec:
        label = block.label_text or ""
        what = f'choice "{label}"'
        _, set_items, emit_items, subs = self.split(block, what, (), ("when", "else"))
        for stray in set_items + emit_items:
            self.at(
                stray, f'"{stray.keyword}" is not allowed directly in a choice; put it in a branch'
            )
        branches: list[BranchSpec] = []
        otherwise: BranchSpec | None = None
        for index, sub in enumerate(subs):
            try:
                spec = self.branch(sub, ctx.derive(where=what), ctx)
                if sub.kind == "else":
                    if index != len(subs) - 1:
                        self.at(sub, f"else must be the last branch of {what}")
                    otherwise = spec
                else:
                    branches.append(spec)
            except _SkipError:
                pass
        if not any(s.kind == "else" for s in subs):
            self.at(block, f"{what} has no else.", 'Add: else { next = "<step>" }')
        if not branches and otherwise is None:
            raise _SkipError()
        spec_c: ChoiceSpec = self.make(
            ChoiceSpec, block, {"name": label, "branches": branches, "otherwise": otherwise}
        )
        spec_c.line, spec_c.column = block.line, block.column
        return spec_c

    def branch(self, block: Block, ctx: _FlowCtx, flow_ctx: _FlowCtx) -> BranchSpec:
        what = "else" if block.kind == "else" else "when"
        attrs, set_items, emit_items, _ = self.split(
            block, f"{what} branch of {ctx.where}", ("next",)
        )
        kwargs: dict[str, Any] = {}
        if block.kind == "when" and block.head is not None:
            self.expr(block.head, ctx)
            kwargs["when"] = self.literal(block.head)
        if "next" in attrs:
            target = self.target_name(attrs["next"], flow_ctx)
            if target is not None:
                kwargs["next"] = target
        else:
            self.at(
                block,
                f"{what} branch of {ctx.where} has no next.",
                'Add: next = "<step>" or next = end',
            )
        kwargs["set"] = self.sets(set_items, ctx)
        kwargs["emit"] = self.emits(emit_items)
        return BranchSpec(**kwargs)

    # -- graph checks --------------------------------------------------------------------------
    def check_graph(self, nodes: list[Any], *, v2: bool = False) -> None:
        if not nodes:
            return
        by_name = {n.name: n for n in nodes}
        edges: dict[str, list[str]] = {}
        for node in nodes:
            out: list[str | None]
            if isinstance(node, ChoiceSpec):
                out = [b.next for b in node.branches]
                if node.otherwise is not None:
                    out.append(node.otherwise.next)
            else:
                out = [node.next, node.on_error, getattr(node, "on_timeout", None)]
            edges[node.name] = [t for t in out if t and t != END and t in by_name]
        reached: list[str] = []
        back_edges: list[tuple[str, str]] = []
        state: dict[str, int] = {}

        def dfs(u: str) -> None:
            state[u] = 1
            reached.append(u)
            for v in edges.get(u, []):
                if v not in state:
                    dfs(v)
                elif state[v] == 1:
                    back_edges.append((u, v))
            state[u] = 2

        dfs(nodes[0].name)
        for node in nodes:
            if node.name not in state and not v2:
                kind = (
                    "step"
                    if isinstance(node, StepSpec)
                    else "parallel" if isinstance(node, ParallelSpec) else "choice"
                )
                self.err(
                    node.line,
                    node.column,
                    f'{kind} "{node.name}" can not be reached from the start',
                )
        # Every cycle must hold a step with max_visits (decision D58).
        for component in _components(reached, edges):
            looped = len(component) > 1 or component[0] in edges.get(component[0], [])
            if not looped:
                continue
            members = set(component)
            if any(isinstance(by_name[m], StepSpec) and by_name[m].max_visits for m in members):
                continue
            edge = next(
                ((u, v) for u, v in back_edges if u in members and v in members),
                (component[0], component[0]),
            )
            step_names = [m for m in reached if m in members and isinstance(by_name[m], StepSpec)]
            target = edge[1] if edge[1] in step_names else (step_names[0] if step_names else None)
            if target is None:
                node = by_name[edge[1]]
                self.err(
                    node.line,
                    node.column,
                    f'"{edge[1]}" is part of a loop that has no step to carry max_visits',
                )
                continue
            node = by_name[target]
            self.err(
                node.line,
                node.column,
                f'step "{target}" can be entered again ({edge[0]} -> {edge[1]}) but has no '
                f"max_visits.",
                "Add: max_visits = 4",
            )

    def check_flow_cycles(self) -> None:
        for start in self.flow_calls:
            path: list[str] = []

            def walk(name: str, start: str = start, path: list[str] = path) -> bool:
                if name in path:
                    return name == start
                if name not in self.flow_calls:
                    return False
                path.append(name)
                for nxt in self.flow_calls[name]:
                    if walk(nxt):
                        return True
                path.pop()
                return False

            if walk(start):
                self.at(
                    self.flow_blocks[start],
                    f'flow "{start}" contains itself ({" -> ".join([*path, start])})',
                )

    # -- prompt --------------------------------------------------------------------------------
    def prompt(self, block: Block) -> PromptSpec:
        if not isinstance(block.label, Str):
            raise self.fail(block, 'a prompt needs a name: prompt "name" { ... }')
        name = block.label.value
        what = f'prompt "{name}"'
        attrs, _, _, subs = self.split(
            block,
            what,
            ("variables", "allow_missing"),
            ("message", "each", "when", "placeholder", "output"),
            v2=_V2_PROMPT,
            v2_message=_V2_MESSAGE,
        )
        variables: list[VariableSpec] = []
        if "variables" in attrs:
            variables = self.variables(attrs["variables"])
        scope = [v.name for v in variables]
        allow: list[str] = []
        if "allow_missing" in attrs:
            value = attrs["allow_missing"].value
            if isinstance(value, ListNode) and all(isinstance(i, Str) for i in value.items):
                for item in value.items:
                    assert isinstance(item, Str)
                    if item.value not in scope:
                        self.at(
                            item,
                            f'allow_missing names "{item.value}", which is not a variable.',
                            did_you_mean(item.value, scope)
                            or "Variables: " + ", ".join(scope) + ".",
                        )
                    else:
                        allow.append(item.value)
            else:
                self.at(value, '"allow_missing" must be a list of variable names: ["style"]')
        # conditional outputs (inside a top-level when) are read with the parts
        self.prompt_variables = variables
        self.conditional_outputs = []
        parts = self.parts(block, scope, top=True, out_ok=True)
        output: OutputSpec | None = None
        plain = [s for s in subs if s.kind == "output"]
        for index, sub in enumerate(plain):
            if index:
                self.at(sub, f"{what} has more than one output block; keep one")
                continue
            try:
                output = self.output(sub, variables)
            except _SkipError:
                pass
        if plain and self.conditional_outputs:
            first = self.conditional_outputs[0]
            self.at(
                first,
                f"{what} has an output block on line {plain[0].line} and one inside a when "
                f"block on line {first.line}; a prompt has either one unconditional output or "
                "conditional ones, not both.",
                "Put every output block inside a when, or keep only the unconditional one.",
            )
        return self.make(  # type: ignore[no-any-return]
            PromptSpec,
            block,
            {
                "name": name,
                "variables": variables,
                "allow_missing": allow,
                "parts": parts,
                "output": output,
            },
        )

    # -- output --------------------------------------------------------------------------------
    def output(self, block: Block, variables: list[VariableSpec]) -> OutputSpec:
        """``output ["json" | "table" | "xml" | VAR] { field = type ["description"], ... }`` or
        ``{ schema = VAR }``.
        """
        fmt: Any = "json"
        format_from: str | None = None
        if isinstance(block.label, Name) and len(block.label.path) == 1:
            format_from = self.format_from(block.label, variables)
        elif block.label is not None:
            if not isinstance(block.label, Str) or block.label.value not in OUTPUT_FORMATS:
                word = block.label_text or ""
                raise self.fail(
                    block.label,
                    f'output format "{word}" is not known.',
                    (did_you_mean(word, OUTPUT_FORMATS) + " Use json, table or xml.").strip(),
                )
            fmt = block.label.value
        items: list[Attribute] = []
        for item in block.body:
            if isinstance(item, Block):
                self.at(
                    item,
                    f'"{item.kind}" is not allowed in an output block.',
                    "Write one field per line: name = string, number, bool, list or map",
                )
            elif item.keyword:
                self.at(item, f'"{item.keyword}" is not allowed in an output block.')
            else:
                items.append(item)
        if any(item.name == _SCHEMA_WORD for item in items):
            schema_from = self.schema_from(items, variables)
            return OutputSpec(format=fmt, format_from=format_from, schema_from=schema_from)
        fields = self.output_fields(items, "output")
        if fmt == "table" and format_from is None:
            for f in fields:
                if f.type not in _SCALARS:
                    self.at(
                        next(i for i in items if i.name == f.name).value,
                        f'output "table": column "{f.name}" is a {f.type}; a table has only '
                        "string, number and bool columns.",
                        'Use output "json" or "xml" for nested data, or make it a string.',
                    )
        if not fields and not items:
            self.at(block, "the output block has no field.", "Add one: name = string")
        return OutputSpec(format=fmt, format_from=format_from, fields=fields)

    def format_from(self, label: Name, variables: list[VariableSpec]) -> str:
        """``output VAR { ... }``: a declared string variable gives the format at render time."""
        word = label.path[0]
        names = [v.name for v in variables]
        declared = next((v for v in variables if v.name == word), None)
        if declared is None:
            hint = did_you_mean(word, names)
            if word in OUTPUT_FORMATS:
                hint = f'Write the format as a string: output "{word}" {{ ... }}'
            raise self.fail(
                label,
                f'variable "{word}" is not declared; it cannot give the output format.',
                (f"Declared: {', '.join(names) or '(none)'}. {hint}").strip(),
            )
        if declared.type != "string":
            raise self.fail(
                label,
                f'the output format comes from "{word}", which is {declared.type}; it must be '
                "a string.",
                f'Declare it as {word} = string("json")',
            )
        if declared.default is not None and declared.default not in OUTPUT_FORMATS:
            raise self.fail(
                label,
                f'the default of "{word}" is "{declared.default}", which is not an output format.',
                (
                    did_you_mean(str(declared.default), OUTPUT_FORMATS) + " Use json, table or xml."
                ).strip(),
            )
        return word

    def schema_from(self, items: list[Attribute], variables: list[VariableSpec]) -> str | None:
        if len(items) > 1:
            other = next(i for i in items if i.name != _SCHEMA_WORD)
            self.err(
                other.name_line,
                other.name_column,
                f'"{_SCHEMA_WORD}" gives all the fields of the output block; it cannot be '
                f'written with other fields ("{other.name}").',
                f'Remove "{other.name}": the fields come from the variable.',
            )
        item = next(i for i in items if i.name == _SCHEMA_WORD)
        if item.description is not None:
            self.at(
                item.description,
                f'"{_SCHEMA_WORD}" takes no description; the fields come from the variable.',
                'Describe them in its value: {"total": {"type": "number", "description": "..."}}',
            )
        value = item.value
        names = [v.name for v in variables]
        if not (isinstance(value, Name) and len(value.path) == 1):
            raise self.fail(
                value,
                f'"{_SCHEMA_WORD}" takes the name of a map variable: {_SCHEMA_WORD} = fields',
            )
        word = value.path[0]
        declared = next((v for v in variables if v.name == word), None)
        if declared is None:
            raise self.fail(
                value,
                f'variable "{word}" is not declared.',
                (f"Declared: {', '.join(names) or '(none)'}. {did_you_mean(word, names)}").strip(),
            )
        if declared.type != "map":
            raise self.fail(
                value,
                f'"{_SCHEMA_WORD}" needs a map variable; "{word}" is {declared.type}.',
                f"Declare it as {word} = map",
            )
        return word

    def output_fields(
        self, items: Sequence[Attribute | MapEntry], where: str
    ) -> list[OutputFieldSpec]:
        out: list[OutputFieldSpec] = []
        seen: set[str] = set()
        for item in items:
            name = item.name if isinstance(item, Attribute) else item.key
            if name in seen:
                self.at(item, f'"{name}" is set twice in {where}')
                continue
            seen.add(name)
            try:
                spec = self.output_field(name, item.value)
            except _SkipError:
                continue
            note = item.description
            if note is not None and not note.value.strip():
                self.at(
                    note,
                    f'the description of "{name}" is empty.',
                    'Write what the field holds, or remove the "".',
                )
            elif note is not None:
                spec = replace(spec, description=note.value)
            out.append(spec)
        return out

    def output_field(self, name: str, value: Value) -> OutputFieldSpec:
        label = f'"{name}"'
        if isinstance(value, MapNode):  # { a = string } is map({ a = string })
            return OutputFieldSpec(name=name, type="map", fields=self.nested(value, name))
        if isinstance(value, ListNode):  # [string] is list(string)
            if len(value.items) != 1:
                raise self.fail(
                    value, f"{label}: a list type has one item type: [string] or [{{ a = string }}]"
                )
            return self.list_field(name, value.items[0])
        if isinstance(value, Name) and len(value.path) == 1:
            word = value.path[0]
            if word in TYPE_NAMES:
                return OutputFieldSpec(name=name, type=word)  # type: ignore[arg-type]
            raise self.fail(
                value,
                f'unknown type "{word}" for {label}.',
                did_you_mean(word, sorted(TYPE_NAMES)) or "Use string, number, bool, list or map.",
            )
        if isinstance(value, TypeCall):
            # list(...)/map(...) with a shape inside (`map({ a = string })`) describes the items;
            # with a plain value (`map({})`, `list([])`) it is an optional field with that default.
            if (
                value.name in ("list", "map")
                and value.default is not None
                and _is_shape(value.default)
            ):
                if value.name == "list":
                    spec = self.list_field(name, value.default)
                elif not isinstance(value.default, MapNode):
                    raise self.fail(
                        value.default, f"{label}: map(...) takes the fields: map({{ a = string }})"
                    )
                else:
                    spec = OutputFieldSpec(
                        name=name, type="map", fields=self.nested(value.default, name)
                    )
                if value.second is None:
                    return spec
                return replace(spec, required=False, default=self.shaped_default(spec, value))
            kind, default = self.typed(value, label, "default")
            return OutputFieldSpec(
                name=name,
                type=kind,  # type: ignore[arg-type]
                default=default,
                required=value.default is None,
            )
        raise self.fail(
            value,
            f"{label} needs a type.",
            "Use string, number, bool, list or map, for example number(0).",
        )

    def list_field(self, name: str, item: Value) -> OutputFieldSpec:
        if isinstance(item, MapNode):
            return OutputFieldSpec(
                name=name, type="list", item_type="map", fields=self.nested(item, name)
            )
        inner = self.output_field(name, item)
        if inner.type == "list" or inner.default is not None:
            raise self.fail(
                item, f'"{name}": the items of a list are string, number, bool or a map {{ ... }}'
            )
        return OutputFieldSpec(
            name=name, type="list", item_type=inner.type, fields=list(inner.fields)
        )

    def nested(self, node: MapNode, name: str) -> list[OutputFieldSpec]:
        if not node.entries:
            raise self.fail(node, f'"{name}": the map has no field. Add one: {{ a = string }}')
        return self.output_fields(node.entries, f'"{name}"')

    def variables(self, attr: Attribute) -> list[VariableSpec]:
        if not isinstance(attr.value, MapNode):
            self.at(attr.value, '"variables" must be a map: variables = { name = string }')
            return []
        out: list[VariableSpec] = []
        for entry in attr.value.entries:
            try:
                spec = self.variable(entry.key, entry.value)
            except _SkipError:
                continue
            note = entry.description
            if note is not None and not note.value.strip():
                self.at(
                    note,
                    f'the description of "{entry.key}" is empty.',
                    'Write what the variable holds, or remove the "".',
                )
            elif note is not None:
                spec = replace(spec, description=note.value)
            out.append(spec)
        return out

    def variable(self, name: str, value: Value) -> VariableSpec:
        """One variable: ``string``, ``number(0)``, ``list([])`` (a default), or a shape with the
        field syntax of ``output``: ``list(string)``, ``list({ ... })``, ``map({ ... })``,
        ``[type]``, ``{ ... }``, with an optional default after it: ``list({ ... }, [])``.
        """
        shaped = isinstance(value, ListNode | MapNode) or (
            isinstance(value, TypeCall)
            and value.name in ("list", "map")
            and value.default is not None
            and _is_shape(value.default)
        )
        if shaped:
            field_spec = self.output_field(name, value)
            return VariableSpec(
                name=name,
                type=field_spec.type,
                default=field_spec.default,
                required=field_spec.required,
                item_type=field_spec.item_type,
                fields=list(field_spec.fields),
            )
        kind, default = self.typed(value, f'"{name}"', "default")
        if isinstance(value, TypeCall):
            self.no_inner_description(value.default)
        has_default = isinstance(value, TypeCall) and value.default is not None
        return VariableSpec(
            name=name,
            type=kind,  # type: ignore[arg-type]
            default=default,
            required=not has_default,
        )

    def shaped_default(self, spec: OutputFieldSpec, value: TypeCall) -> Any:
        """The default after a shape (``list({ ... }, [])``), checked against the shape."""
        assert value.second is not None
        self.no_inner_description(value.second)
        default = self.literal(value.second)
        errors: list[str] = []
        conform(spec.type, spec.item_type, spec.fields, default, spec.name, errors)
        if errors:
            raise self.fail(
                value.second,
                f'the default of "{spec.name}" does not match its shape: {"; ".join(errors)}',
                f"Use an empty {'list: []' if spec.type == 'list' else 'map: {}'}, or values "
                "with every required field.",
            )
        return default

    def no_inner_description(self, node: Value | None) -> None:
        """Only a variable (or a field of a shape) takes a description, not a default value."""
        if isinstance(node, TypeCall):
            self.no_inner_description(node.default)
        elif isinstance(node, ListNode):
            for item in node.items:
                self.no_inner_description(item)
        elif isinstance(node, MapNode):
            for entry in node.entries:
                if entry.description is not None:
                    self.at(
                        entry.description,
                        f'"{entry.key}" is a key of a default value and takes no description.',
                        'Describe the variable instead: name = map({ ... }) "What it holds"',
                    )
                self.no_inner_description(entry.value)

    def parts(
        self, block: Block, scope: list[str], *, top: bool, out_ok: bool = False
    ) -> list[PromptPartSpec]:
        """The parts of a prompt, message, ``when`` or ``each`` block. ``out_ok`` is true in the
        prompt and in a ``when`` reached from it through ``when`` blocks only: there an ``output``
        block is a conditional output.
        """
        out: list[PromptPartSpec] = []
        allowed_blocks = ("message", "each", "when", "placeholder") if top else ("each", "when")
        for item in block.body:
            try:
                if isinstance(item, Attribute):
                    if block.kind == "prompt":
                        continue  # the attributes of the prompt itself were read already
                    if item.name == "text" and not top and not item.keyword:
                        out.append(self.text_part(item, scope))
                    elif item.name in _V2_PROMPT:
                        self.err(
                            item.name_line,
                            item.name_column,
                            _V2_MESSAGE.format(item.name),
                        )
                    else:
                        self.unknown(item, item.name, f"{block.kind} block", ["text"])
                    continue
                if block.kind == "prompt":
                    if item.kind in allowed_blocks:
                        out.append(self.part_block(item, scope, top=top, out_ok=out_ok))
                    continue  # others were reported by split; output was read by prompt()
                if item.kind in _V2_PROMPT:
                    self.at(item, _V2_MESSAGE.format(item.kind))
                elif item.kind == "output" and out_ok:
                    self.conditional_outputs.append(item)
                    output = self.output(item, self.prompt_variables)
                    out.append(PromptPartSpec(kind="output", output=output))
                elif item.kind == "output" and not top:
                    self.at(
                        item,
                        "an output block belongs to the prompt, not to a message.",
                        "Move it out of the message, into the prompt block or a top-level when.",
                    )
                elif item.kind == "output":
                    self.at(
                        item,
                        "an output block cannot be inside an each block.",
                        "Move it into the prompt block, or into a when at the top of the prompt.",
                    )
                elif item.kind not in allowed_blocks:
                    self.unknown(item, item.kind, f"{block.kind} block", [*allowed_blocks, "text"])
                else:
                    out.append(self.part_block(item, scope, top=top, out_ok=out_ok))
            except _SkipError:
                pass
        return out

    def part_block(
        self, item: Block, scope: list[str], *, top: bool, out_ok: bool = False
    ) -> PromptPartSpec:
        if item.kind == "placeholder":
            if not isinstance(item.label, Str):
                raise self.fail(item, 'a placeholder needs a name: placeholder "history"')
            return PromptPartSpec(kind="placeholder", name=item.label.value)
        if item.kind == "message":
            label = item.label
            role: str | None
            role_from: Any = None
            if isinstance(label, Str):
                if label.value not in _ROLES:
                    raise self.fail(
                        label,
                        f'role "{label.value}" is not valid.',
                        "Use system, user or assistant",
                    )
                role = label.value
            elif isinstance(label, Name):
                self.prompt_name(label.path, label.line, label.column, scope)
                role = None
                role_from = Expression(text=label.text, line=label.line, column=label.column)
            else:
                raise self.fail(item, 'a message needs a role: message "system" { ... }')
            children = self.parts(item, scope, top=False)
            return PromptPartSpec(kind="message", role=role, role_from=role_from, children=children)
        assert item.head is not None
        self.prompt_expr(item.head, scope)
        if item.kind == "when":
            return PromptPartSpec(
                kind="when",
                condition=self.literal(item.head),
                children=self.parts(item, scope, top=top, out_ok=out_ok and top),
            )
        return PromptPartSpec(
            kind="each",
            variable=item.var,
            items=self.literal(item.head),
            # inside an each, `loop` (index, index0, first, last, length) is defined too
            children=self.parts(item, [*scope, item.var, "loop"], top=top),
        )

    def text_part(self, item: Attribute, scope: list[str]) -> PromptPartSpec:
        if not isinstance(item.value, Str):
            raise self.fail(item.value, '"text" must be a string in quotes')
        self.interpolation(item.value, scope)
        return PromptPartSpec(kind="text", text=item.value.value)

    def prompt_name(self, chain: tuple[str, ...], line: int, col: int, scope: list[str]) -> None:
        if chain[0] not in scope and chain[0] not in _PROMPT_LITERALS:
            self.err(
                line,
                col,
                f'variable "{chain[0]}" is not declared.',
                (
                    f"Declared: {', '.join(scope) or '(none)'}. " f"{did_you_mean(chain[0], scope)}"
                ).strip(),
            )

    def prompt_expr(self, node: Value, scope: list[str]) -> None:
        if isinstance(node, Name):
            self.prompt_name(node.path, node.line, node.column, scope)
        elif isinstance(node, Expr):
            problems = check_expression(
                node.text, filename=self.file, line=node.line, column=node.column
            )
            if problems:
                self.errors.extend(problems)
                return
            for chain, ref in references(node.text):
                line, col = locate(node.text, ref, node.line, node.column)
                self.prompt_name(chain, line, col, scope)

    def interpolation(self, node: Str, scope: list[str]) -> None:
        text = node.value
        if "{%" in text:
            self.at(
                node,
                'control tags "{% %}" are not used in a prompt block.',
                "Use a when or each block.",
            )
        rest = text
        while "{{" in rest:
            _, _, rest = rest.partition("{{")
            inner, closed, rest = rest.partition("}}")
            if not closed:
                self.at(node, 'a "{{" has no closing "}}"')
                return
            match = re.match(r"\s*([A-Za-z_]\w*)", inner)
            if match and match.group(1) not in scope and match.group(1) not in _PROMPT_LITERALS:
                word = match.group(1)
                self.at(
                    node,
                    f'variable "{word}" is not declared.',
                    (
                        f"Declared: {', '.join(scope) or '(none)'}. " f"{did_you_mean(word, scope)}"
                    ).strip(),
                )


def _is_shape(node: Value) -> bool:
    """True when ``node`` is a type (``string``, ``[string]``, ``{ a = string }``,
    ``string("x")``) and not a value (``[]``, ``{}``, ``["a"]``, ``{ a = 1 }``). A default value
    holds no bare word, so ``{ a = strin }`` is a shape with an unknown type.
    """
    if isinstance(node, Name):  # a bare word is a type (a misspelt one is reported as such)
        return len(node.path) == 1
    if isinstance(node, TypeCall):
        return node.name in TYPE_NAMES
    if isinstance(node, ListNode):
        return len(node.items) == 1 and _is_shape(node.items[0])
    if isinstance(node, MapNode):
        return bool(node.entries) and all(_is_shape(e.value) for e in node.entries)
    return False


def _uses_v2(block: Block) -> bool:
    """True when a block has a ``wait`` or ``on_event`` (words reserved for version 2)."""
    for item in block.body:
        if isinstance(item, Attribute) and item.name in _V2_FLOW:
            return True
        if isinstance(item, Block) and item.kind in _V2_FLOW:
            return True
    return False


def _infer_ast(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int | float):
            return "number"
        if isinstance(node.value, str):
            return "string"
        return None
    if isinstance(node, ast.List | ast.Tuple):
        return "list"
    if isinstance(node, ast.Dict):
        return "map"
    if isinstance(node, ast.Compare) or (
        isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    ):
        return "bool"
    if isinstance(node, ast.UnaryOp):
        return _infer_ast(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = _infer_ast(node.left), _infer_ast(node.right)
        if left == right == "number":
            return "number"
        if left == right == "string" and isinstance(node.op, ast.Add):
            return "string"
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return {"str": "string", "len": "number", "int": "number", "float": "number"}.get(
            node.func.id
        )
    if isinstance(node, ast.IfExp):
        body, other = _infer_ast(node.body), _infer_ast(node.orelse)
        return body if body == other else None
    return None


def _components(nodes: list[str], edges: dict[str, list[str]]) -> list[list[str]]:
    """The strongly connected components (Tarjan) of the reachable graph, in discovery order."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, []):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            result.append(comp)

    for v in nodes:
        if v not in index:
            visit(v)
    return result


def build(
    source: str | Tree,
    *,
    filename: str | None = None,
    registry_names: Collection[str] | None = None,
) -> Document:
    """Parse (if given text) and validate a ``.skye`` file into block models.

    Args:
        source: The ``.skye`` text, or a tree from :func:`skye.base.dsl.parse`.
        filename: The name used in diagnostics when ``source`` is text.
        registry_names: The names the caller will pass in its registry. When given, every
            ``registry.NAME`` is checked against them; when ``None`` they are not checked.

    Returns:
        A :class:`Document` with the sound blocks and every diagnostic. It does not raise; call
        :meth:`Document.raise_for_errors` to turn the diagnostics into one exception.
    """
    errors: list[Diagnostic] = []
    name = filename or (source.filename if isinstance(source, Tree) else None) or DEFAULT_FILENAME
    try:
        if isinstance(source, Tree):
            tree = source
        else:
            tree, errors = parse_collect(source, filename)
        if (
            errors
        ):  # a text that does not parse is reported as is; checks on a partial tree would mislead
            return Document(filename=tree.filename or DEFAULT_FILENAME, diagnostics=errors)
        return _Builder(tree, registry_names).build()
    except RecursionError:  # the last safety net: a file must never end in a traceback
        return Document(
            filename=name,
            diagnostics=[
                Diagnostic(
                    file=name,
                    line=1,
                    column=1,
                    reason=too_deep_reason(),
                    fix=TOO_DEEP_FIX,
                )
            ],
        )


def check_text(
    text: str,
    filename: str | None = None,
    registry_names: Collection[str] | None = None,
) -> list[Diagnostic]:
    """Every mistake in a ``.skye`` text (syntax and load-time checks); empty when it is valid.

    Args:
        text: The ``.skye`` text (this function reads no file).
        filename: The name used in diagnostics.
        registry_names: Known names for ``registry.NAME`` (``None`` = do not check them).
    """
    return build(text, filename=filename, registry_names=registry_names).diagnostics


__all__ = ["END", "PREFIXES", "Document", "build", "check_text"]
