"""The block models of the ``.skye`` language, as validated dataclasses.

They are the meaning of a file: :mod:`skye.base.dsl.build` fills them from the syntax tree after
the load-time checks. Field names are 1:1 with today's router configuration (``ModelTarget``,
``RouteConfig``, ``FallbackConfig``, ``RetryPolicyConfig``, the allowed-fails policy); a name that
ended in ``_seconds`` drops the suffix and takes a duration string such as ``"30s"``.

Values that are not literals (references such as ``context.url`` and expressions) are kept as
:class:`~skye.base.dsl.expressions.Expression` objects; an ``env.NAME`` in a router block becomes
the
text ``${NAME}``, which the router configuration already substitutes.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from skye.base.validated import Validated, field, validated

#: The built-in routing strategies (the values of ``skye.base.interfaces.router.RoutingStrategy``). A name that a plugin registered is also valid
#: in a ``strategy`` (the checker asks the registrar), which is why the fields below are ``Strategy | str``.
Strategy = Literal[
    "simple_shuffle",
    "round_robin",
    "least_busy",
    "rate_limit_aware",
    "latency_based",
    "cost_based",
    "weighted",
    "priority_based",
]
STRATEGIES: tuple[str, ...] = (
    "simple_shuffle",
    "round_robin",
    "least_busy",
    "rate_limit_aware",
    "latency_based",
    "cost_based",
    "weighted",
    "priority_based",
)

#: A duration: a number and a unit (``30s``, ``5m``, ``24h``, ``2d``).
DURATION = re.compile(r"^(\d+(?:\.\d+)?)(s|m|h|d)$")
_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(text: str) -> float:
    """The seconds in a duration string.

    Args:
        text: A duration such as ``"30s"``, ``"5m"``, ``"24h"`` or ``"2d"``.

    Raises:
        ValueError: If ``text`` is not a duration.
    """
    match = DURATION.match(text.strip())
    if match is None:
        raise ValueError(f'{text!r} is not a duration; use "30s", "5m" or "24h"')
    return float(match.group(1)) * _UNITS[match.group(2)]


def format_duration(seconds: float) -> str:
    """A duration string for a number of seconds, in the largest unit that divides it exactly.

    Args:
        seconds: A non-negative number of seconds.

    Returns:
        For example ``"30s"``, ``"5m"``, ``"24h"``, ``"2d"`` or ``"1.5s"``; :func:`parse_duration`
        gives the seconds back.

    Raises:
        ValueError: If ``seconds`` is negative.
    """
    if seconds < 0:
        raise ValueError(f"a duration cannot be negative: {seconds!r}")
    for unit, size in (("d", 86400.0), ("h", 3600.0), ("m", 60.0)):
        if seconds and seconds % size == 0:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s" if float(seconds).is_integer() else f"{float(seconds)!r}s"


# -- router ------------------------------------------------------------------------------------


@validated
class TargetSpec(Validated):
    """A model target of a route (``target { ... }`` or one entry of the shorthand)."""

    model: str = field(description="Actual model identifier")
    provider: str = field(description="Provider name")
    api_key: str | None = field(default=None, description="API key (env.NAME becomes ${NAME})")
    api_base: str | None = field(default=None, description="Base URL for API calls")
    api_version: str | None = field(default=None, description="API version (Azure)")
    region: str | None = field(default=None, description="Deployment region")
    timeout: str | None = field(
        default=None, description='Request timeout, a duration such as "30s"'
    )
    max_retries: int | None = field(default=None, ge=0, description="Maximum retry attempts")
    weight: float = field(default=1.0, ge=0, description="Weight for weighted routing")
    tpm: int | None = field(default=None, ge=0, description="Tokens per minute limit")
    rpm: int | None = field(default=None, ge=0, description="Requests per minute limit")
    cost_per_1k_prompt_tokens: float | None = field(
        default=None, ge=0, description="Price of 1000 prompt tokens (read by cost_based)"
    )
    cost_per_1k_completion_tokens: float | None = field(
        default=None, ge=0, description="Price of 1000 completion tokens (read by cost_based)"
    )
    tags: list[str] = field(default_factory=list, description="Tags for routing")
    metadata: dict[str, Any] = field(default_factory=dict, description="Additional metadata")
    options: dict[str, Any] = field(
        default_factory=dict,
        description="Keyword arguments for the provider client (project_id, location, endpoint)",
    )


@validated
class RouteSpec(Validated):
    """A route: an alias, its targets, the strategy that picks among them and its fallback chain."""

    alias: str = field(description="Alias name of the route")
    targets: list[TargetSpec] = field(default_factory=list, description="Targets of the route")
    strategy: Strategy | str | None = field(
        default=None, description="Strategy that picks a target"
    )
    fallback_on_error: bool = field(default=True, description="Try the next target on error")
    fallback: list[str] = field(
        default_factory=list, description="Routes to try, in order, when this route fails"
    )
    fallback_targets: list[TargetSpec] = field(
        default_factory=list,
        description='Shorthand only: the entries after the first of route "x" = [...]',
    )


@validated
class RetryPolicySpec(Validated):
    """``retry_policy "<error>" { ... }``: how many times to retry one kind of error."""

    error_type: str = field(description="Error type, for example RateLimitError")
    max_retries: int = field(default=0, ge=0, description="Maximum retry attempts")
    retry_after: str | None = field(default=None, description='Delay between retries, "5s"')
    exponential_backoff: bool = field(default=False, description="Double the delay each time")


@validated
class AllowedFailsPolicySpec(Validated):
    """``allowed_fails_policy "<error>" { ... }``: failures per minute before a cooldown."""

    error_type: str = field(description="Error type")
    allowed_fails_per_minute: int = field(ge=0, description="Allowed failures per minute")


@validated
class RouterSpec(Validated):
    """A ``router`` block."""

    name: str | None = field(default=None, description="The label of the block, if any")
    strategy: Strategy | str | None = field(default=None, description="Default routing strategy")
    cooldown: str | None = field(default=None, description='Cooldown after failures, "60s"')
    enable_pre_call_checks: bool = field(
        default=True, description="Check rate limits before a call"
    )
    routes: list[RouteSpec] = field(default_factory=list, description="The routes")
    retry_policies: list[RetryPolicySpec] = field(
        default_factory=list, description="Retry policies"
    )
    allowed_fails_policies: list[AllowedFailsPolicySpec] = field(
        default_factory=list, description="Cooldown policies"
    )


# -- flow --------------------------------------------------------------------------------------

#: The types a context field or a prompt variable may have.
FieldType = Literal["string", "number", "bool", "list", "map"]


@validated
class ContextFieldSpec(Validated):
    """One typed field of the ``context`` block."""

    name: str = field(description="Field name")
    type: FieldType = field(description="string, number, bool, list or map")
    default: Any = field(default=None, description="Default value")
    required: bool = field(default=True, description="True when there is no default")


@validated
class ContextSpec(Validated):
    """The ``context`` block: the typed fields a flow reads and sets."""

    fields: list[ContextFieldSpec] = field(default_factory=list, description="Declared fields")


@validated
class RetrySpec(Validated):
    """``retry = { max = 3, after = "2s", backoff = true }`` (``retry = 3``
    means ``{ max = 3 }``).
    """

    max: int = field(default=0, ge=0, description="Maximum retries")
    after: str | None = field(default=None, description='Delay before a retry, "2s"')
    backoff: bool = field(default=False, description="Double the delay each time")


@validated
class SetSpec(Validated):
    """``set field = expr``: runs when the step finishes with success."""

    name: str = field(description="The declared context field to change")
    value: Any = field(default=None, description="A literal or an expression")


@validated
class StepSpec(Validated):
    """A ``step`` block."""

    name: str = field(description="Step name")
    run: str | None = field(
        default=None, description="registry.NAME, flow.NAME or router.NAME (a Runnable)"
    )
    input: dict[str, Any] = field(default_factory=dict, description="Input of the Runnable")
    next: str | None = field(default=None, description='Next step, or "end"')
    on_error: str | None = field(default=None, description="Step to go to on error")
    on_timeout: str | None = field(default=None, description="Step to go to on timeout")
    timeout: str | None = field(default=None, description='Timeout, "30s"')
    retry: RetrySpec | None = field(default=None, description="Retry of the step itself")
    max_visits: int | None = field(
        default=None, ge=1, description="Bound for a step re-entered in a loop"
    )
    foreach: Any = field(default=None, description="Run once for each item of this list")
    set: list[SetSpec] = field(default_factory=list, description="Context changes on success")
    emit: list[str] = field(default_factory=list, description="Events emitted on success")
    line: int = field(default=0, init=False, repr=False, compare=False)
    column: int = field(default=0, init=False, repr=False, compare=False)


@validated
class ParallelSpec(Validated):
    """A ``parallel`` block: branch steps that run at the same time."""

    name: str = field(description="Block name")
    join: Literal["all", "any"] = field(default="all", description="all or any")
    on_branch_error: Literal["cancel", "continue"] = field(
        default="cancel", description="cancel the others, or continue"
    )
    steps: list[StepSpec] = field(default_factory=list, description="The branches")
    next: str | None = field(default=None, description='Next step, or "end"')
    on_error: str | None = field(default=None, description="Step to go to on error")
    line: int = field(default=0, init=False, repr=False, compare=False)
    column: int = field(default=0, init=False, repr=False, compare=False)


@validated
class BranchSpec(Validated):
    """A branch of a ``choice``: ``when <expr> { ... }`` (``when`` is empty for ``else``)."""

    when: Any = field(default=None, description="The condition (an expression); None for else")
    next: str | None = field(default=None, description='Next step, or "end"')
    set: list[SetSpec] = field(default_factory=list, description="Context changes")
    emit: list[str] = field(default_factory=list, description="Events emitted")


@validated
class ChoiceSpec(Validated):
    """A ``choice`` block: branches checked in order, and a mandatory ``else``."""

    name: str = field(description="Block name")
    branches: list[BranchSpec] = field(default_factory=list, description="The when branches")
    otherwise: BranchSpec | None = field(default=None, description="The else branch")
    line: int = field(default=0, init=False, repr=False, compare=False)
    column: int = field(default=0, init=False, repr=False, compare=False)


@validated
class FlowSpec(Validated):
    """A ``flow`` block. ``nodes`` are the steps, parallels and choices; the
    first one is the start.
    """

    name: str = field(description="Flow name")
    context: ContextSpec = field(default_factory=ContextSpec, description="Declared context")
    nodes: list[Any] = field(
        default_factory=list, description="StepSpec, ParallelSpec and ChoiceSpec, in file order"
    )

    @property
    def start(self) -> str | None:
        """The name of the first node (where the flow starts)."""
        return self.nodes[0].name if self.nodes else None

    def node(self, name: str) -> Any:
        """The step, parallel or choice called ``name`` (``None`` if there is none)."""
        for item in self.nodes:
            if item.name == name:
                return item
        return None


# -- prompt ------------------------------------------------------------------------------------


@validated
class VariableSpec(Validated):
    """One variable of a prompt.

    A string after the type is the ``description`` (``task = string "What the agent must
    achieve"``); ``describe_prompt`` and ``skye prompt info`` show it.

    A structured variable takes the field syntax of the ``output`` block:
    ``tags = list(string)``, ``categories = list({ name = string, note = string("") })``,
    ``owner = map({ team = string })`` (or ``[string]``, ``[{ ... }]``, ``{ ... }``). It is
    required; ``list({ ... }, [])`` gives a default (the second argument). ``render_prompt``
    checks the value given against the shape and fills the defaults of the optional fields.
    """

    name: str = field(description="Variable name")
    type: FieldType = field(default="string", description="string, number, bool, list or map")
    default: Any = field(default=None, description="Default value")
    required: bool = field(default=True, description="True when there is no default")
    description: str | None = field(
        default=None, description='What the variable holds: task = string "The goal"'
    )
    item_type: FieldType | None = field(
        default=None, description="list(string) or list({ ... }): the type of the items"
    )
    fields: list[Any] = field(
        default_factory=list,
        description="OutputFieldSpec: the fields of map({ ... }), or of the items of list({ ... })",
    )

    @property
    def structured(self) -> bool:
        """True for ``list(<type>)``, ``list({ ... })`` and ``map({ ... })``: values are checked."""
        return self.item_type is not None or bool(self.fields)


#: The formats of an ``output`` block (``output "json" { ... }``; no label means ``"json"``).
OutputFormat = Literal["json", "table", "xml"]
OUTPUT_FORMATS: tuple[str, ...] = ("json", "table", "xml")


@validated
class OutputFieldSpec(Validated):
    """One field of an ``output`` block, possibly nested.

    ``total = number`` gives ``type="number"``; ``currency = string("EUR")`` adds a ``default``;
    ``lines = list({ description = string })`` gives ``type="list"``, ``item_type="map"`` and the
    item fields in ``fields``; ``tags = list(string)`` gives ``item_type="string"``;
    ``meta = map({ source = string })`` gives ``type="map"`` and its ``fields``. A bare ``list``
    or ``map`` has no ``item_type`` or ``fields`` (any items, any keys). A string after the type
    is the ``description`` (``total = number "Total amount including VAT"``); it goes into the
    schema given to the model.
    """

    name: str = field(description="Field name")
    type: FieldType = field(description="string, number, bool, list or map")
    default: Any = field(default=None, description="Default value (string, number or bool)")
    required: bool = field(default=True, description="True when there is no default")
    item_type: FieldType | None = field(
        default=None, description="The type of the items of a list (None: any)"
    )
    fields: list[Any] = field(
        default_factory=list,
        description="OutputFieldSpec: the fields of a map, or of the items of a list of maps",
    )
    description: str | None = field(
        default=None, description="What the field holds, for the model (the string after the type)"
    )


@validated
class OutputSpec(Validated):
    """The ``output`` block of a prompt: the shape of the answer and the format to write it in.

    The renderer turns it into instructions for the model (see
    ``skye.prompts.output_instructions``); nobody writes the structure by hand.
    """

    format: OutputFormat = field(
        default="json", description="json, table or xml (not read when format_from is set)"
    )
    format_from: str | None = field(
        default=None,
        description="output VAR { ... }: the string variable that gives the format at render time",
    )
    fields: list[OutputFieldSpec] = field(
        default_factory=list, description="The fields of the answer, in order"
    )
    schema_from: str | None = field(
        default=None,
        description="schema = VAR: the map variable that gives the fields at render time",
    )


@validated
class PromptPartSpec(Validated):
    """One part of a prompt: a message, a text, a ``when`` or ``each`` block, a placeholder, or
    an ``output`` block inside a top-level ``when`` (a conditional output).
    """

    kind: Literal["message", "text", "when", "each", "placeholder", "output"] = field(
        description="Kind of part"
    )
    role: str | None = field(default=None, description="system, user or assistant (message)")
    role_from: Any = field(default=None, description="An expression that gives the role (message)")
    text: str | None = field(default=None, description="The text, with {{ }} (text)")
    condition: Any = field(default=None, description="The condition (when)")
    variable: str | None = field(default=None, description="The loop variable (each)")
    items: Any = field(default=None, description="The list to loop over (each)")
    name: str | None = field(default=None, description="The placeholder name (placeholder)")
    children: list[Any] = field(default_factory=list, description="Parts inside the block")
    output: OutputSpec | None = field(
        default=None, description="The output block (output, inside a top-level when)"
    )


@validated
class PromptSpec(Validated):
    """A ``prompt`` block of version 1 (variables, messages, text, when, each, placeholder,
    output).
    """

    name: str = field(description="Prompt name")
    variables: list[VariableSpec] = field(default_factory=list, description="Declared variables")
    allow_missing: list[str] = field(
        default_factory=list, description="Variables the caller may leave out"
    )
    parts: list[PromptPartSpec] = field(default_factory=list, description="Messages, in order")
    output: OutputSpec | None = field(
        default=None,
        description="The unconditional output block: format and fields of the answer (None when "
        "there is none, or when the outputs are inside when blocks)",
    )

    def output_variants(self) -> list[tuple[list[Any], OutputSpec]]:
        """Every output block with the conditions that make it active, in the order written.

        The unconditional block has no condition (``[]``); a conditional one, written inside a
        top-level ``when`` (or a ``when`` nested in one), has the conditions of its ``when``
        blocks from the outside in. A prompt has one or the other, never both.
        """
        if self.output is not None:
            return [([], self.output)]
        out: list[tuple[list[Any], OutputSpec]] = []

        def walk(parts: list[Any], conditions: list[Any]) -> None:
            for part in parts:
                if part.kind == "output" and part.output is not None:
                    out.append((conditions, part.output))
                elif part.kind == "when":
                    walk(part.children, [*conditions, part.condition])

        walk(self.parts, [])
        return out
