# task 7.3, decision D76, D60
"""Role-based message building for Skye prompts (structure).

Holds `BasePromptBuilder`, the PromptBuilderInterface implementation that renders
templates into role-based SkyeMessage objects (formerly `prompts/base.py`).
Template discovery lives in `skye.prompts.loaders`.

Follows the liteprompt design (loaders, role-based messages, registry, truncation) with a
standard-library template engine (`skye.prompts.engine`) instead of Jinja2, so the
serverless runtime needs no compiled or third-party template dependency.

Three kinds of template text are accepted:

* block templates (``{{ name }}`` with filters), rendered by the engine; interpolation only: a
  ``{% %}`` control tag is rejected at registration, conditions and loops are
  written in a ``.skye`` prompt;
* simple templates (``{name}``), rendered with ``str.format``;
* ``.skye`` prompt text (a ``prompt "name" { ... }`` block), rendered by
  ``skye.prompts.skye_prompts.render_prompt``.

Every template is parsed once, at registration; the compiled form and its variable names are
kept, the text itself only once (``get_template`` returns it).
"""

from __future__ import annotations

import base64
import binascii
import copy
import dataclasses
import json
import logging
import math
import random
import re
import string
import threading
import types
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from skye.base.config import substitute_env_vars
from skye.base.dsl.info import (
    InputInfo,
    OutputInfo,
    PromptInfo,
    describe_prompt,
    fields_from_json_schema,
    prompt_help,
)
from skye.base.dsl.metadata import split_metadata
from skye.base.exceptions import ValidationError
from skye.base.interfaces.prompt import PromptBuilderInterface
from skye.base.messages import (
    AssistantMessage,
    CapabilityMessage,
    CapabilityStatus,
    SkyeMessage,
    SystemMessage,
    UserMessage,
)
from skye.base.plugins import get_registrar
from skye.base.prompt_parts import OutputSchema, PromptParts
from skye.base.validated import trusted
from skye.prompts.engine import CompiledTemplate, TemplateSyntaxError, compile_template
from skye.base.dsl.include import INCLUDE_LINE, Resolver
from skye.prompts.loaders import catalogue_resolver, load_default_templates
from skye.prompts.output_format import check_format, format_instructions

# The role-based message types are re-exported from here so peers (e.g. the `tools` MCP client's
# prompt facet, Requirement 15) can consume the `prompts` prompt type without reaching into `base`.
__all__ = [
    "BasePromptBuilder",
    "CapabilityMessage",
    "SkyeMessage",
    "UserMessage",
    "SystemMessage",
    "AssistantMessage",
    "DEFAULT_MAX_EXAMPLES",
]

logger = logging.getLogger(__name__)

#: How many examples are used when no selector (or a selector without ``max_examples``) is set.
DEFAULT_MAX_EXAMPLES = 5
#: How many formatted example texts (fixed selection) are kept; the oldest is dropped first.
DEFAULT_EXAMPLE_CACHE_SIZE = 256

VALID_ROLES: tuple[str, ...] = ("system", "user", "assistant", "capability")
SELECTOR_TYPES: tuple[str, ...] = ("fixed", "random", "semantic")
IMAGE_FORMATS: tuple[str, ...] = ("url", "base64", "path")
CONTENT_TYPES: tuple[str, ...] = ("text", "image", "audio", "video", "file", "document")
_JSON_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})

_BLOCK_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.DOTALL)
# A whole line ``[WORD]``, ``[WORD arg ...]`` or ``[WORD:arg]``.
_MARKER_RE = re.compile(r"^\[(\w+)(?:[\s:]+([^\]]*))?\]$")
_ROLE_MARKERS = {
    "SYSTEM": "system",
    "USER": "user",
    "ASSISTANT": "assistant",
    "CAPABILITY": "capability",
}
_PLACEHOLDER_MARKER = "PLACEHOLDER"


@dataclass(frozen=True, slots=True)
class _TemplateEntry:
    """What registration keeps of one template besides its text."""

    kind: Literal["block", "simple", "skye"]
    variables: tuple[str, ...]
    required: tuple[str, ...]
    compiled: CompiledTemplate | None = None
    spec: Any = None  # a ``PromptSpec`` for ``kind == "skye"``


#: The compiled bundled templates of the process, so that a second builder compiles nothing. The key is the name, the version, the path, the size and the
#: modification time of the file, and the fingerprint of the catalogue when the template includes a partial. An entry is immutable and a cached ``.skye``
#: spec is read-only (see ``skye.base.dsl.cache``), so builders can share them.
_BUNDLED_ENTRIES: dict[tuple[Any, ...], _TemplateEntry] = {}
_BUNDLED_LOCK = threading.RLock()


def _wants_example_list(spec: Any) -> bool:
    """False when the ``.skye`` prompt declares ``examples`` as a string (formatted text)."""
    for var in getattr(spec, "variables", None) or []:
        if var.name == "examples":
            return bool(var.type != "string")
    return True


class _Blank:
    """Value of an allowed-missing variable in a simple template: formats as the empty text."""

    def __format__(self, spec: str) -> str:
        return ""

    def __str__(self) -> str:
        return ""

    def __getattr__(self, name: str) -> _Blank:
        return self

    def __getitem__(self, key: Any) -> _Blank:
        return self


_BLANK = _Blank()


class BasePromptBuilder(PromptBuilderInterface):
    """Base implementation of PromptBuilderInterface.

    Registers the bundled templates (the ``.skye`` files of the templates folder; each is compiled at its first use) and renders
    templates into ``SkyeMessage`` objects that every provider accepts.

    Features:
    - Versioned registry (``name:version``), templates parsed once: at registration, and the bundled ones at their first use
    - Block templates (stdlib engine), simple ``{name}`` templates and ``.skye`` prompts
    - Default values (``${VAR}`` substituted), callable defaults, allowed-missing variables
    - Few-shot examples with fixed, random and semantic (embedder callable) selectors
    - Role sections (``[SYSTEM]``, ``[USER]``, ``[ASSISTANT]``, ``[CAPABILITY name id]``) and
      message placeholders (``[PLACEHOLDER name]``) for conversation histories
    - Image content (URL, base64, path) attached to the user message
    - Output schema from a dataclass or a JSON-schema dictionary

    Args:
        max_cached_examples: How many formatted example texts are kept (fixed selection).

    Example:
        >>> builder = BasePromptBuilder()
        >>> builder.register_template("greet", "Hello {{ name }}!")
        >>> builder.render("greet", {"name": "Ada"})[0].content
        'Hello Ada!'
    """

    def __init__(self, *, max_cached_examples: int = DEFAULT_EXAMPLE_CACHE_SIZE) -> None:
        """Initialize with the bundled templates (registered now, compiled at their first use)."""
        self._templates: dict[str, str] = {}
        self._entries: dict[str, _TemplateEntry] = {}
        # Bundled ``.skye`` templates that are registered and not compiled yet: key -> (path, size, modification time). See ``_entry``.
        self._pending: dict[str, tuple[Path, int, int]] = {}
        # What a template that includes files was built with: key -> (resolver, file name, key of the file). See ``validate_template``.
        self._includes: dict[str, tuple[Resolver, str | None, str | None]] = {}
        self._latest: dict[str, str] = {}
        self._template_metadata: dict[str, dict[str, Any]] = {}
        self._defaults: dict[str, Any] = {}
        self._allowed_missing: set[str] = set()
        self._partial_vars: dict[str, Any] = {}
        self._examples: dict[str, list[dict[str, Any]]] = {}
        self._example_templates: dict[str, str] = {}
        self._example_entries: dict[str, _TemplateEntry] = {}
        self._examples_as_messages: set[str] = set()
        self._example_selectors: dict[str, dict[str, Any]] = {}
        self._example_cache: OrderedDict[str, str] = OrderedDict()
        self._example_vectors: dict[str, list[list[float]]] = {}
        self._max_cached_examples = max_cached_examples
        self._content_configs: dict[str, dict[str, str]] = {}
        self._role_mappings: dict[str, dict[str, str]] = {}
        self._message_placeholders: dict[str, dict[str, str]] = {}
        self._output_schemas: dict[str, Any] = {}
        self._schema_json: dict[str, dict[str, Any]] = {}
        self._output_formats: dict[str, str] = {}
        # The default set (Requirement 56.8): the filters that plugins registered with ``registrar.template_filter``. It is read at the first use of
        # the filters (see ``_custom_filters``), so a builder that only lists or reads templates does not wait for the registrar to load its built-ins.
        self._filters: dict[str, Callable[..., Any]] | None = None

        # Default allowed missing variables for block templates
        self.set_allowed_missing_variables([
            "examples", "max_length", "guidelines", "history",
            "description", "output_format", "system_prompt", "domain", "labels",
            "categories", "context", "question", "text", "input", "tools",
            "episodic_memory", "semantic_memory",
            "persona_memory", "working_memory", "tools_output", "procedural_memory",
            "constraints", "requirements", "programming_language", "task_type",
            "code_context", "error_message", "code_style", "capabilities",
            "personality", "response_guidelines", "thinking_required",
            "content_types", "images", "documents", "audio",
            "database_schema", "database_type", "relation_types", "table_schema",
            "extraction_rules",
            "form_description", "form_fields", "current_field",
            "collected_data", "validation_errors", "form_progress", "form_complete",
            "reasoning_type", "output_format", "task", "language"
        ])  # fmt: skip

        self._register_default_templates()

    @property
    def _custom_filters(self) -> dict[str, Callable[..., Any]]:
        """The filters of this builder: the default set (read once, at the first use) and the filters added with ``register_filter``.

        A filter added with ``register_filter`` stays local to this builder and wins over a default of the same name.
        """
        filters = self._filters
        if filters is None:
            filters = self._filters = dict(get_registrar().default_set("template_filter"))
        return filters

    @_custom_filters.setter
    def _custom_filters(self, value: dict[str, Callable[..., Any]]) -> None:
        self._filters = value

    # ------------------------------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------------------------------

    def render(self, template_name: str, variables: dict[str, Any]) -> list[SkyeMessage]:
        """Render a template into messages.

        Args:
            template_name: The template (its latest version is used).
            variables: The values; they win over partial variables, which win over defaults.

        Returns:
            One message per role section (a single ``UserMessage`` when there is none).

        Raises:
            KeyError: If the template is not registered.
            ValidationError: (a ``ValueError``) If required variables are missing (all are
                named), a role marker is unknown or content is invalid.
        """
        return self._render(template_name, variables, instructions=True)[0]

    # Requirement 33.9, decision D101
    def render_parts(self, template_name: str, variables: dict[str, Any]) -> PromptParts:
        """Render a template into provider-agnostic parts.

        Give the result to ``client.complete(parts, model=...)``: the model adapter puts the
        system text and the output schema in the provider's own fields, or falls back to the text.

        Args:
            template_name: The template (its latest version is used).
            variables: The values, as for :meth:`render`.

        Returns:
            ``system``: the text of the system messages (``None`` when there is none);
            ``messages``: the other messages, as :meth:`render` gives them but without the output
            instructions of a ``.skye`` ``output`` block; ``output``: the JSON Schema of a
            ``json`` output (from :meth:`set_output_schema`, else the ``.skye`` ``output``
            block) as an ``OutputSchema`` named after the template, ``None`` for free text,
            ``table`` and ``xml``; ``fallback_text``: the output instructions
            (:meth:`get_output_instructions`), ``None`` when there are none.

        Raises:
            KeyError: If the template is not registered.
            ValidationError: As :meth:`render`.
        """
        from skye.prompts.output_format import format_instructions
        from skye.prompts.skye_prompts import _active_fields, schema_name, split_system

        messages, entry, merged = self._render(template_name, variables, instructions=False)
        schema: dict[str, Any] | None = self._schema_json.get(template_name)
        output_format = self._output_formats.get(template_name, "json")
        fallback = ""
        if schema is not None:
            fallback = self.get_output_instructions(template_name, variables)
        elif entry.kind == "skye":
            active = _active_fields(entry.spec, merged)
            if active is not None:
                output_format, schema = active
                fallback = format_instructions(schema, output_format, entry.spec.name)
        output = None
        if schema is not None and output_format == "json":
            output = OutputSchema(name=schema_name(template_name), schema=schema)
        return split_system(messages, output, fallback or None)

    def _render(
        self, template_name: str, variables: Mapping[str, Any], *, instructions: bool
    ) -> tuple[list[SkyeMessage], _TemplateEntry, dict[str, Any]]:
        """The messages, the entry and the merged variables of one rendering."""
        key = self._latest_key(template_name)
        entry = self._entry(key)
        merged = self._merge_variables(list(entry.variables), variables)
        as_messages = template_name in self._examples_as_messages
        if template_name in self._examples and "examples" not in variables and not as_messages:
            if entry.kind == "skye" and _wants_example_list(entry.spec):
                merged["examples"] = self._select_examples(template_name, merged)
            else:
                merged["examples"] = self._examples_text(template_name, merged)

        if entry.kind == "skye":
            messages = self._render_skye(template_name, entry, merged, instructions=instructions)
        else:
            self._check_required(template_name, entry, merged)
            text = self._render_text(template_name, key, entry, merged)
            messages = self._create_messages(template_name, text, merged)
        if as_messages:
            self._insert_example_messages(template_name, messages, merged)
        self._apply_content(template_name, messages, merged)
        return messages, entry, merged

    def partial(self, **kwargs: str | Callable[[], str]) -> BasePromptBuilder:
        """Return a new builder with ``kwargs`` bound; this builder is left unchanged.

        A callable value is called once, now. The registry is shared by reference (entries are
        immutable), every configuration dictionary is copied.
        """
        new_builder = copy.copy(self)
        for attr, value in vars(self).items():
            if isinstance(value, dict | set | list):
                setattr(new_builder, attr, value.copy())
        for key, value in kwargs.items():
            new_builder._partial_vars[key] = value() if callable(value) else value
        return new_builder

    def invoke(self, template_name: str, variables: dict[str, Any]) -> list[SkyeMessage]:
        """Same as :meth:`render`."""
        return self.render(template_name, variables)

    def format(self, template_name: str, variables: dict[str, Any]) -> str:
        """Render and join the message texts with a newline."""
        messages = self.render(template_name, variables)
        return "\n".join(msg.content for msg in messages if hasattr(msg, "content"))

    # ------------------------------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------------------------------

    def register_template(
        self,
        name: str,
        template: str,
        version: str = "1.0",
        from_string: bool = True,
        resolver: Resolver | None = None,
    ) -> None:
        """Parse and register a template under ``name:version``.

        A ``.skye`` text (a file ending in ``.skye``, or a text whose first line that is not a
        comment starts with ``prompt "``) is built with ``skye.base.dsl.build``; the prompt called
        ``name`` (or the only prompt of the text) is kept.

        Args:
            name: Template name.
            template: The text, or a file path when ``from_string`` is False.
            version: Version; the latest is the greatest in string order.
            from_string: False to read ``template`` as a file path. A ``.skye`` file read from a path may ``include``, ``from``
                ``import``, ``use`` and ``override`` files of its own folder; they are read again at each registration.
            resolver: Reads the includes of a text (``resolver(target, from_key) -> Resolved``); a file path gets the file resolver
                of its folder when this is omitted, and a text without a resolver cannot include.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValidationError: (a ``ValueError``) If the template does not parse; the message has
                the parser's details and the template name.
        """
        filename: str | None = None
        origin: str | None = None
        if from_string:
            content = template
        else:
            path = Path(template)
            content = path.read_text(encoding="utf-8")
            filename = str(path)
            if resolver is None and INCLUDE_LINE.search(content):
                from skye.utils.skye_files import file_resolver

                resolver, origin = file_resolver(path), str(path.resolve())

        entry = self._compile_entry(name, content, filename, resolver, origin)
        key = f"{name}:{version}"
        if resolver is None:
            self._includes.pop(key, None)
        else:
            self._includes[key] = (resolver, filename, origin)
        self._pending.pop(key, None)
        self._templates[key] = content
        self._entries[key] = entry
        self._template_metadata[key] = {"name": name, "version": version, "format": entry.kind}
        latest = self._latest.get(name)
        if latest is None or version >= latest:
            self._latest[name] = version
        logger.debug(
            "Registered prompt template",
            extra={"template": name, "version": version, "format": entry.kind},
        )

    def register_bundled_template(
        self,
        name: str,
        text: str,
        path: Path,
        version: str = "1.0",
        stamp: tuple[int, int] | None = None,
    ) -> None:
        """Register a bundled ``.skye`` template without compiling it; it is compiled at its first use.

        The text, the name and the version are kept now, so listing and reading the template cost nothing. A mistake in the
        template shows at the first use, as the same ``ValidationError`` that ``register_template`` raises. The build of a
        bundled template does not validate its objects (``skye.base.validated.trusted``): it was checked in development.

        Args:
            name: Template name.
            text: The text of the file.
            path: The file, also used as the name in the diagnostics (for an entry of the archive of an installed wheel, the
                name of the archive and of the entry).
            version: Version; the latest is the greatest in string order.
            stamp: The size and the modification time of the source, for the cache of the process; read from ``path`` when
                omitted (an entry of an archive has no file of its own, so the caller gives it).
        """
        key = f"{name}:{version}"
        if stamp is None:
            status = path.stat()
            stamp = (status.st_size, status.st_mtime_ns)
        self._entries.pop(key, None)
        self._pending[key] = (path, stamp[0], stamp[1])
        self._templates[key] = text
        self._template_metadata[key] = {"name": name, "version": version, "format": "skye"}
        latest = self._latest.get(name)
        if latest is None or version >= latest:
            self._latest[name] = version

    def _entry(self, key: str) -> _TemplateEntry:
        """The compiled entry of ``name:version``; a pending bundled template is compiled now, once, and kept.

        Raises:
            ValidationError: The pending template does not compile (the error is not kept: the next use raises it again).
        """
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        pending = self._pending.get(key)
        if pending is None:
            raise KeyError(key)
        path, size, mtime = pending
        meta = self._template_metadata[key]
        with _BUNDLED_LOCK:
            entry = self._entries.get(key)
            if entry is not None:  # another thread compiled it while this one waited
                return entry
            text = self._templates[key]
            resolver = catalogue_resolver if INCLUDE_LINE.search(text) else None
            fingerprint = resolver.fingerprint() if resolver else None
            cache_key = (meta["name"], meta["version"], str(path), size, mtime, fingerprint)
            entry = _BUNDLED_ENTRIES.get(cache_key)
            if entry is None:
                with trusted():
                    extra = (resolver, Path(path).name) if resolver else ()  # a template with no include keeps the 3 arguments
                    entry = _compile_skye(meta["name"], text, str(path), *extra)
                _BUNDLED_ENTRIES[cache_key] = entry
            self._entries[key] = entry
            self._pending.pop(key, None)
        return entry

    def get_template(self, name: str, version: str | None = None) -> str:
        """Return the template text (the latest version, or the given one).

        Raises:
            KeyError: If the template or version is not registered.
        """
        if version is None:
            return self._templates[self._latest_key(name)]
        key = f"{name}:{version}"
        if key not in self._templates:
            raise KeyError(f"Template not found: {key}")
        return self._templates[key]

    def get_template_variables(self, template_name: str) -> list[str]:
        """Return the variable names of a template, in first-seen order.

        For a block template these are the free names the engine finds in ``{{ }}`` (the root of
        ``{{ user.name }}``, the operands of filters and conditional expressions); for a ``.skye``
        prompt the declared variables.
        """
        return list(self._entry(self._latest_key(template_name)).variables)

    def set_default_values(self, defaults: dict[str, Any]) -> None:
        """Set default values (a callable is called at each rendering).

        Defaults usually come from configuration, so ``${VAR}`` in a string (also inside lists and
        dictionaries) is replaced by the environment variable ``VAR`` here, once.

        Raises:
            ConfigurationError: If a ``${VAR}`` names an environment variable that is not set.
        """
        self._defaults.update({k: _substitute(v) for k, v in defaults.items()})
        self._example_cache.clear()

    def set_allowed_missing_variables(self, variables: list[str]) -> None:
        """Add variables that may be left out (they render as empty text)."""
        self._allowed_missing.update(variables)

    def compose_templates(
        self, name: str, template_parts: list[str], separator: str = "\n\n"
    ) -> None:
        """Register ``name`` as the texts of ``template_parts`` joined with ``separator``.

        Raises:
            KeyError: If a part is not registered.
            ValidationError: If a part is a ``.skye`` prompt (compose those in the ``.skye`` file).
        """
        parts: list[str] = []
        for part in template_parts:
            key = self._latest_key(part)
            if self._entry(key).kind == "skye":
                raise ValidationError(
                    f"Cannot compose the .skye prompt '{part}' as text",
                    field="template_parts",
                    value=part,
                )
            parts.append(self._templates[key])
        self.register_template(name, separator.join(parts))

    # ------------------------------------------------------------------------------------------
    # Examples
    # ------------------------------------------------------------------------------------------

    # decision D79
    def add_examples(
        self,
        template_name: str,
        examples: list[dict[str, Any]],
        example_template: str | None = None,
        *,
        as_messages: bool = False,
    ) -> None:
        """Store few-shot examples; they are injected as the variable ``examples`` or as messages.

        A ``.skye`` prompt that declares ``examples`` as a list (or does not declare it as a
        string) gets the selected examples as a list of dictionaries, unformatted; a text template,
        or a ``.skye`` prompt with ``examples = string``, gets them as text: written with
        ``example_template`` when given, else from each example's own keys, one ``Key: value``
        line per key in order (``{"question": "Hello", "answer": "Bonjour"}`` gives
        ``Question: Hello`` and ``Answer: Bonjour``). With ``as_messages=True`` each example
        becomes a user message and an assistant message instead, inserted before the last user
        message: the values of ``input`` and ``output`` when the example has both, otherwise its
        first key for the user and its last key for the assistant. Selection (limit, random,
        semantic) applies to every form.

        Args:
            template_name: Template the examples belong to.
            examples: The examples (dictionaries).
            example_template: How one example is written: ``{key}`` or ``{{ key }}`` style.
            as_messages: Give each example as a user/assistant message pair.

        Raises:
            ValidationError: If the example template does not parse, an example lacks a key it
                reads (the example's index and the keys are named), ``as_messages`` is combined
                with an example template, or an example given as messages has fewer than two
                keys.
        """
        examples = list(examples)
        if as_messages:
            if example_template is not None:
                raise ValidationError(
                    "add_examples: as_messages=True writes each example as messages; "
                    "do not pass an example_template too",
                    field="example_template",
                    value=example_template,
                    template=template_name,
                )
            for index, example in enumerate(examples):
                _example_turns(template_name, index, example)
            self._example_entries.pop(template_name, None)
            self._example_templates.pop(template_name, None)
            self._examples_as_messages.add(template_name)
        elif example_template is not None:
            entry = self._compile_text(f"{template_name}:examples", example_template)
            for index, example in enumerate(examples):
                missing = [key for key in entry.required if key not in example]
                if missing:
                    raise ValidationError(
                        f"add_examples: example {index} of template '{template_name}' lacks "
                        f"{', '.join(repr(k) for k in missing)}, read by the example template",
                        field="examples",
                        value=missing,
                        template=template_name,
                        example=index,
                        missing=missing,
                    )
            self._example_entries[template_name] = entry
            self._example_templates[template_name] = example_template
            self._examples_as_messages.discard(template_name)
        else:
            self._example_entries.pop(template_name, None)
            self._example_templates.pop(template_name, None)
            self._examples_as_messages.discard(template_name)
        self._examples[template_name] = examples
        self._forget_examples(template_name)

    def set_example_selector(
        self,
        template_name: str,
        selector_type: str,
        max_examples: int = DEFAULT_MAX_EXAMPLES,
        **selector_kwargs: Any,
    ) -> None:
        """Choose how examples are selected.

        Args:
            template_name: The template.
            selector_type: ``"fixed"`` (the first ones), ``"random"`` or ``"semantic"``.
            max_examples: At most this many examples are used.
            **selector_kwargs: For ``"semantic"``: ``embedder`` (required, a callable
                ``(str) -> list[float]``), ``input_key`` (the variable holding the query;
                default ``input``, else the first text variable) and ``example_key`` (the example
                field compared; default ``input_key``, then ``input``, then every text field).
                Text values have ``${VAR}`` substituted.

        Raises:
            ValidationError: For an unknown selector type (the supported ones are listed), a
                negative ``max_examples`` or a semantic selector without an embedder.
        """
        if selector_type not in SELECTOR_TYPES:
            raise ValidationError(
                f"Unknown example selector type '{selector_type}'. "
                f"Supported: {', '.join(SELECTOR_TYPES)}",
                field="selector_type",
                value=selector_type,
            )
        if not isinstance(max_examples, int) or max_examples < 0:
            raise ValidationError(
                "max_examples must be an integer of at least 0",
                field="max_examples",
                value=max_examples,
            )
        if selector_type == "semantic" and not callable(selector_kwargs.get("embedder")):
            raise ValidationError(
                "The semantic example selector needs embedder=<callable (str) -> list[float]>",
                field="embedder",
                value=selector_kwargs.get("embedder"),
            )
        kwargs = {
            k: (_substitute(v) if isinstance(v, str) else v) for k, v in selector_kwargs.items()
        }
        self._example_selectors[template_name] = {
            **kwargs,
            "type": selector_type,
            "max_examples": max_examples,
        }
        self._forget_examples(template_name)

    # ------------------------------------------------------------------------------------------
    # Content, filters, roles
    # ------------------------------------------------------------------------------------------

    def add_image_content(
        self, template_name: str, image_variable: str, image_format: str = "url"
    ) -> None:
        """Attach the variable ``image_variable`` as image(s) to the user message.

        At rendering the value (one image or a list) is checked: ``url`` is an http(s) URL or a
        ``data:`` URI, ``base64`` must decode (it becomes bytes), ``path`` must exist (it becomes a
        ``Path``). The images go into ``UserMessage.images``.

        Raises:
            ValidationError: For a format not in ``url``, ``base64``, ``path``.
        """
        _check_image_format(image_format, image_variable)
        self._content_configs.setdefault(template_name, {})[
            image_variable
        ] = f"image:{image_format}"

    def add_multimodal_content(self, template_name: str, content_variables: dict[str, str]) -> None:
        """Declare the content type of variables (``type`` or ``image:<format>``).

        Raises:
            ValidationError: For a type not in text, image, audio, video, file, document, or an
                image format not in url, base64, path.
        """
        checked: dict[str, str] = {}
        for variable, content_type in content_variables.items():
            kind, _, fmt = str(content_type).partition(":")
            if kind not in CONTENT_TYPES:
                raise ValidationError(
                    f"Unsupported content type '{content_type}' for '{variable}'. "
                    f"Supported types: {', '.join(CONTENT_TYPES)}",
                    field=variable,
                    value=content_type,
                )
            if kind == "image" and fmt:
                _check_image_format(fmt, variable)
            checked[variable] = content_type
        self._content_configs.setdefault(template_name, {}).update(checked)

    # D77
    def register_filter(self, filter_name: str, filter_func: Callable[[Any], Any]) -> None:
        """Register a filter for ``{{ value | name }}``, in text and ``.skye`` prompts."""
        self._custom_filters[filter_name] = filter_func
        self._example_cache.clear()

    def set_message_roles(self, template_name: str, role_mapping: dict[str, str]) -> None:
        """Map section markers to roles.

        ``{"context": "system"}`` makes a line ``[CONTEXT]`` (or ``[context]``) start a system
        message.

        Raises:
            ValidationError: For a role not in system, user, assistant, capability.
        """
        for section, role in role_mapping.items():
            _check_role(role, section)
        self._role_mappings[template_name] = dict(role_mapping)

    def add_message_placeholder(
        self, template_name: str, placeholder_name: str, role: str = "user"
    ) -> None:
        """Insert the history in the variable ``placeholder_name`` at rendering.

        The history (a list of ``SkyeMessage``, of ``{"role", "content"}`` dictionaries, or of
        texts that take ``role``) goes at a line ``[PLACEHOLDER name]`` of the template, or before
        the last user message when there is no such line.

        Raises:
            ValidationError: For a role not in system, user, assistant, capability.
        """
        _check_role(role, placeholder_name)
        self._message_placeholders.setdefault(template_name, {})[placeholder_name] = role

    def capability_message(
        self,
        name: str,
        call_id: str,
        result: Any,
        status: CapabilityStatus | str = CapabilityStatus.OK,
    ) -> CapabilityMessage:
        """Build the message that returns a capability result to the model.

        Args:
            name: Capability name.
            call_id: Identifier of the capability call.
            result: The result; anything but a string is written as JSON.
            status: How the call ended.

        Returns:
            A ``CapabilityMessage``.
        """
        content = result if isinstance(result, str) else _to_json(result)
        return CapabilityMessage(
            content=content,
            capability_name=name,
            capability_id=call_id,
            status=CapabilityStatus(status),
        )

    # ------------------------------------------------------------------------------------------
    # Schema, metadata, validation
    # ------------------------------------------------------------------------------------------

    def set_output_schema(
        self, template_name: str, schema: dict[str, Any] | type, output_format: str = "json"
    ) -> None:
        """Set the output schema: a dataclass or a JSON-schema dictionary.

        Args:
            template_name: The template.
            schema: A dataclass or a JSON-schema dictionary.
            output_format: The format the model answers in: ``"json"`` (the default, the
                instructions list the fields and give the JSON schema), ``"table"`` (a Markdown
                table; every field must be a string, number or bool) or ``"xml"`` (a skeleton
                whose root element is the template name).

        Raises:
            ValidationError: If ``schema`` is neither, or the dictionary is not a JSON schema
                (it needs ``type`` or ``properties``), or ``output_format`` is not json, table or
                xml, or a table has a nested (list or object) field.
        """
        if check_format(output_format) == "text":
            raise ValidationError(
                "output_format 'text' has no fields: use output \"text\" in a .skye prompt",
                field="output_format",
                value=output_format,
            )
        if isinstance(schema, type) and dataclasses.is_dataclass(schema):
            json_schema = _dataclass_schema(schema, set())
        elif isinstance(schema, Mapping):
            _check_json_schema(schema, "schema")
            json_schema = dict(schema)
        else:
            raise ValidationError(
                "The output schema must be a dataclass or a JSON-schema dictionary",
                field="schema",
                value=repr(schema),
            )
        if output_format != "json":
            format_instructions(json_schema, output_format, template_name)  # fails early
        self._output_schemas[template_name] = schema
        self._schema_json[template_name] = json_schema
        self._output_formats[template_name] = output_format

    def get_output_instructions(
        self, template_name: str, variables: Mapping[str, Any] | None = None
    ) -> str:
        """Return the instructions for the model.

        With a schema from :meth:`set_output_schema`: in ``json`` every field and the JSON schema,
        in ``table`` and ``xml`` the shape to answer in. Else, for a ``.skye`` prompt with an
        ``output`` block, the text :func:`skye.prompts.output_instructions` gives (``variables``,
        merged with the defaults and partial variables, feed ``schema = VAR``). Else empty.
        """
        schema = self._schema_json.get(template_name)
        if schema is None:
            return self._skye_output_instructions(template_name, variables or {})
        output_format = self._output_formats.get(template_name, "json")
        if output_format != "json":
            return format_instructions(schema, output_format, template_name)
        fields = list(_schema_fields(schema, "", True))
        lines: list[str] = []
        if fields:
            lines.append("Respond with JSON only: an object with these fields:")
            for path, sub, required in fields:
                kind = _type_label(sub)
                line = f"- {path} ({kind}{', required' if required else ', optional'})"
                if sub.get("description"):
                    line += f": {sub['description']}"
                lines.append(line)
        else:
            lines.append(f"Respond with JSON only: a value of type {_type_label(schema)}.")
        lines.append("")
        lines.append("JSON schema:")
        lines.append(json.dumps(schema, ensure_ascii=False))
        return "\n".join(lines)

    def _skye_output_instructions(self, template_name: str, variables: Mapping[str, Any]) -> str:
        """The instructions of the ``output`` block of a ``.skye`` prompt ("" if there is none)."""
        if template_name not in self._latest:
            return ""
        entry = self._entry(self._latest_key(template_name))
        if entry.kind != "skye" or not entry.spec.output_variants():
            return ""
        from skye.prompts.skye_prompts import output_instructions

        merged = self._merge_variables(list(entry.variables), variables)
        return output_instructions(entry.spec, merged)

    def get_template_metadata(self, template_name: str) -> dict[str, Any]:
        """Return metadata; ``variables`` and ``optional_variables`` together list exactly the
        variables found in the template."""
        entry = self._entry(self._latest_key(template_name))
        required = self._required_names(entry)
        variables = [v for v in entry.variables if v in required]
        return {
            "variables": variables,
            "optional_variables": [v for v in entry.variables if v not in required],
            "format": entry.kind,
            "has_examples": template_name in self._examples,
            "content_types": list(self._content_configs.get(template_name, {}).values()),
            "message_roles": list(self._role_mappings.get(template_name, {}).values()),
            "output_schema": self._output_schemas.get(template_name),
            "example_count": len(self._examples.get(template_name, [])),
        }

    def describe(self, template_name: str) -> PromptInfo:
        """What a registered template takes and gives back (its latest version).

        A ``.skye`` prompt is read with :func:`skye.prompts.describe_prompt` and the front matter
        of its text (title, description, tags; the version is the registered one). A text
        template lists the variables the engine finds (required unless allowed-missing or given a
        default; type ``any``; defaults from :meth:`set_default_values` and :meth:`partial`), its
        ``[ROLE]`` / ``[PLACEHOLDER x]`` markers (``["user"]`` without markers) and the
        placeholders of :meth:`add_message_placeholder`. A schema from
        :meth:`set_output_schema` gives the output (for a ``.skye`` prompt too, as at rendering).

        Raises:
            KeyError: If the template is not registered.
        """
        key = self._latest_key(template_name)
        entry = self._entry(key)
        version = self._template_metadata[key]["version"]
        if entry.kind == "skye":
            metadata, _, _ = split_metadata(self._templates[key], template_name)
            info = describe_prompt(entry.spec, {**metadata, "version": version})
        else:
            info = self._describe_text(template_name, entry, version)
        schema = self._schema_json.get(template_name)
        if schema is not None:
            output = OutputInfo(
                format=self._output_formats.get(template_name, "json"),
                fields=fields_from_json_schema(schema),
            )
            info = dataclasses.replace(info, output=output)
        return info

    def help(self, template_name: str) -> str:
        """The help of a registered template as aligned plain text (see :meth:`describe`).

        Raises:
            KeyError: If the template is not registered.
        """
        return prompt_help(self.describe(template_name))

    def _describe_text(self, name: str, entry: _TemplateEntry, version: str) -> PromptInfo:
        required = self._required_names(entry)
        inputs = []
        for var in entry.variables:
            default = self._partial_vars.get(var, self._defaults.get(var))
            if callable(default):
                default = None
            given = var in self._partial_vars or var in self._defaults
            inputs.append(
                InputInfo(
                    name=var,
                    required=var in required and not given,
                    default=default,
                    allow_missing=var in self._allowed_missing,
                )
            )
        mapping = {k.lower(): v for k, v in self._role_mappings.get(name, {}).items()}
        roles: list[str] = []
        placeholders: list[str] = []
        for line in self._templates[f"{name}:{version}"].splitlines():
            match = _MARKER_RE.match(line.strip())
            word = match.group(1) if match else ""
            if word.lower() in mapping:
                roles.append(mapping[word.lower()])
            elif word in _ROLE_MARKERS:
                roles.append(_ROLE_MARKERS[word])
            elif word == _PLACEHOLDER_MARKER and match and (match.group(2) or "").split():
                placeholder = (match.group(2) or "").split()[0]
                roles.append(placeholder)
                placeholders.append(placeholder)
        roles = roles or ["user"]
        for placeholder in self._message_placeholders.get(name, {}):
            if placeholder not in placeholders:
                placeholders.append(placeholder)
                last_user = max((i for i, r in enumerate(roles) if r == "user"), default=None)
                roles.insert(len(roles) if last_user is None else last_user, placeholder)
        return PromptInfo(
            name=name,
            version=version,
            inputs=inputs,
            placeholders=placeholders,
            roles=roles,
        )

    def validate_template(self, template_name: str) -> dict[str, Any]:
        """Parse the template again and report; never raises.

        Returns:
            ``valid``, ``errors`` (the parser's messages), ``warnings`` (required variables
            without a default) and ``variables_found``.
        """
        try:
            key = self._latest_key(template_name)
            resolver, filename, origin = self._includes.get(key, (None, None, None))
            entry = self._compile_entry(template_name, self._templates[key], filename, resolver, origin)
        except KeyError as e:
            return _validation(False, [f"Template not found: {e.args[0] if e.args else e}"])
        except ValidationError as e:
            return _validation(False, [e.message])
        except Exception as e:  # validation never raises (Requirement 29.6)
            return _validation(False, [f"{type(e).__name__}: {e}"])
        warnings = [
            f"Variable '{var}' has no default value"
            for var in entry.variables
            if var in self._required_names(entry)
            and var not in self._defaults
            and var not in self._partial_vars
        ]
        return _validation(True, [], warnings, list(entry.variables))

    # ------------------------------------------------------------------------------------------
    # Helpers: registry
    # ------------------------------------------------------------------------------------------

    def _register_default_templates(self) -> None:
        """Register the bundled templates of the templates folder; the ``.skye`` ones are compiled at their first use."""
        load_default_templates(self)

    def _is_block_template(self, template: str) -> bool:
        """True when the text uses ``{{ }}`` or ``{# #}`` (or a ``{% %}`` tag, then rejected)."""
        return bool(_BLOCK_RE.search(template))

    def _compile_entry(
        self,
        name: str,
        text: str,
        filename: str | None,
        resolver: Resolver | None = None,
        key: str | None = None,
    ) -> _TemplateEntry:
        """Parse a template text of any kind."""
        if (filename is not None and filename.endswith(".skye")) or _looks_like_skye(text):
            if resolver is None:  # a template with no include keeps the 3 arguments
                return _compile_skye(name, text, filename)
            return _compile_skye(name, text, filename, resolver, key)
        return self._compile_text(name, text)

    def _compile_text(self, name: str, text: str) -> _TemplateEntry:
        """Parse a block or simple template."""
        if self._is_block_template(text):
            try:
                compiled = compile_template(text)
            except TemplateSyntaxError as e:
                details: dict[str, Any] = {"template": name}
                if e.line is not None:
                    details["line"] = e.line
                raise ValidationError(
                    f"Invalid template '{name}': {e}", field="template", value=name, **details
                ) from e
            return _TemplateEntry(
                "block", compiled.variables, compiled.required_variables, compiled
            )
        try:
            names = _simple_fields(text)
        except ValueError as e:
            raise ValidationError(
                f"Invalid template '{name}': {_brace_message(str(e))}",
                field="template",
                value=name,
                template=name,
            ) from e
        return _TemplateEntry("simple", names, names)

    def _latest_key(self, name: str) -> str:
        """The ``name:version`` key of the latest version; ``KeyError`` if there is none."""
        version = self._latest.get(name)
        if version is None:
            raise KeyError(f"Template not found: {name}")
        return f"{name}:{version}"

    def _get_latest_template(self, name: str) -> str:
        """Get latest version of template."""
        return self._templates[self._latest_key(name)]

    def _extract_variables(self, template: str) -> list[str]:
        """Extract the variable names of a template text with the engine's parser."""
        return list(self._compile_entry("template", template, None).variables)

    def _required_names(self, entry: _TemplateEntry) -> set[str]:
        """Variables that must be given (not allowed-missing, read unconditionally)."""
        if entry.kind == "skye":
            return set(entry.required)
        return {v for v in entry.required if v not in self._allowed_missing}

    # ------------------------------------------------------------------------------------------
    # Helpers: rendering
    # ------------------------------------------------------------------------------------------

    def _merge_variables(
        self, template_vars: list[str], provided_vars: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Defaults, then partial variables, then the provided ones (the provided ones win)."""
        merged: dict[str, Any] = {}
        # A default that is a function is called at each rendering (Requirement 30.4): the
        # provided variables still win.
        # A default hidden by a partial or provided variable is not called.
        for k, v in self._defaults.items():
            if k not in provided_vars and k not in self._partial_vars:
                merged[k] = v() if callable(v) else v
        merged.update({k: v for k, v in self._partial_vars.items() if k not in provided_vars})
        merged.update(provided_vars)
        return merged

    def _check_required(
        self, template_name: str, entry: _TemplateEntry, merged: Mapping[str, Any]
    ) -> None:
        missing = sorted(v for v in self._required_names(entry) if v not in merged)
        if not missing:
            return
        label = "variable" if len(missing) == 1 else "variables"
        raise ValidationError(
            f"Missing required {label}: {', '.join(missing)} (template '{template_name}')",
            field="variables",
            value=missing,
            template=template_name,
        )

    def _render_text(
        self, template_name: str, key: str, entry: _TemplateEntry, merged: Mapping[str, Any]
    ) -> str:
        """Render a block or simple template (allowed-missing variables become empty)."""
        filled = dict(merged)
        try:
            if entry.compiled is not None:
                for var in entry.variables:
                    if var in self._allowed_missing:
                        filled.setdefault(var, "")
                return entry.compiled.render(filled, self._custom_filters)
            for var in entry.variables:
                if var in self._allowed_missing:
                    filled.setdefault(var, _BLANK)
            return self._templates[key].format_map(filled)
        except TemplateSyntaxError as e:
            raise ValidationError(
                f"Template rendering failed for '{template_name}': {e}",
                field="template",
                value=template_name,
            ) from e
        except (KeyError, IndexError, AttributeError) as e:
            raise ValidationError(
                f"Template rendering failed for '{template_name}': {e!r}",
                field="template",
                value=template_name,
            ) from e

    def _render_skye(
        self,
        template_name: str,
        entry: _TemplateEntry,
        merged: dict[str, Any],
        *,
        instructions: bool = True,
    ) -> list[SkyeMessage]:
        """Render a ``.skye`` prompt with ``skye.prompts.skye_prompts.render_prompt`` (or without
        the output instructions, for :meth:`render_parts`)."""
        from skye.prompts.skye_prompts import render_prompt

        placeholders = self._message_placeholders.get(template_name, {})
        history: dict[str, list[SkyeMessage]] = {}
        for name in _spec_placeholders(entry.spec.parts):
            if merged.get(name) is not None:
                history[name] = self._history(name, merged, placeholders.get(name, "user"))
        variables = {k: v for k, v in merged.items() if k not in history}
        if instructions:
            messages = list(
                render_prompt(
                    entry.spec,
                    variables,
                    history=history or None,
                    filters=self._custom_filters or None,
                )
            )
        else:
            from skye.prompts.skye_prompts import render_parts

            parts = render_parts(
                entry.spec,
                variables,
                history=history or None,
                filters=self._custom_filters or None,
            )
            system = [SystemMessage(content=parts.system)] if parts.system else []
            messages = [*system, *parts.messages]
        rest = {k: v for k, v in placeholders.items() if k not in history}
        self._insert_histories(messages, rest, merged)
        return messages

    def _create_messages(
        self, template_name: str, content: str, variables: Mapping[str, Any] | None = None
    ) -> list[SkyeMessage]:
        """Split the rendered text into role sections and build one message per section."""
        variables = variables or {}
        mapping = {k.lower(): v for k, v in self._role_mappings.get(template_name, {}).items()}
        placeholders = self._message_placeholders.get(template_name, {})
        messages: list[SkyeMessage] = []
        inserted: set[str] = set()

        if mapping or self._has_role_markers(content, mapping):
            for item in self._parse_role_sections(content, mapping):
                if item[0] == _PLACEHOLDER_MARKER:
                    name = item[1]
                    messages.extend(self._history(name, variables, placeholders.get(name, "user")))
                    inserted.add(name)
                    continue
                role, args, text = item
                text = text.strip()
                if text:
                    messages.append(_make_message(role, args, text))
            if not messages and not inserted:
                messages = [UserMessage(content=content)]
        else:
            messages = [UserMessage(content=content)]

        rest = {k: v for k, v in placeholders.items() if k not in inserted}
        self._insert_histories(messages, rest, variables)
        return messages

    def _insert_histories(
        self,
        messages: list[SkyeMessage],
        placeholders: Mapping[str, str],
        variables: Mapping[str, Any],
    ) -> None:
        """Insert each placeholder history before the last user message (or at the end)."""
        for name, role in placeholders.items():
            history = self._history(name, variables, role)
            if not history:
                continue
            index = next(
                (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "user"),
                len(messages),
            )
            messages[index:index] = history

    def _history(self, name: str, variables: Mapping[str, Any], role: str) -> list[SkyeMessage]:
        """The messages of the placeholder ``name``: SkyeMessage, dictionaries or texts."""
        value = variables.get(name)
        if value is None or value == "":
            return []
        if isinstance(value, str | bytes) or not isinstance(value, Iterable):
            raise ValidationError(
                f"The placeholder '{name}' needs a list of messages",
                field=name,
                value=type(value).__name__,
            )
        out: list[SkyeMessage] = []
        for item in value:
            if isinstance(item, SkyeMessage):
                out.append(item)
            elif isinstance(item, Mapping):
                data = dict(item)
                data.setdefault("role", role)
                _check_role(data["role"], name)
                out.append(SkyeMessage.from_dict(data))
            elif isinstance(item, str):
                out.append(_make_message(role, [], item))
            else:
                raise ValidationError(
                    f"The placeholder '{name}' has an entry that is not a message",
                    field=name,
                    value=type(item).__name__,
                )
        return out

    def _has_role_markers(self, content: str, mapping: Mapping[str, str] | None = None) -> bool:
        """True when a line is a marker: ``[SYSTEM]``, ``[PLACEHOLDER x]``, an uppercase word or a
        mapped section name."""
        for line in content.splitlines():
            match = _MARKER_RE.match(line.strip())
            if match and (match.group(1).isupper() or match.group(1).lower() in (mapping or {})):
                return True
        return False

    def _parse_role_sections(
        self, content: str, mapping: Mapping[str, str] | None = None
    ) -> list[tuple[Any, ...]]:
        """Split at marker lines into ``(role, args, text)`` sections and
        ``("PLACEHOLDER", name)`` items.

        Raises:
            ValidationError: For an unknown uppercase marker (the valid roles are listed).
        """
        mapping = mapping or {}
        items: list[tuple[Any, ...]] = []
        role: str = "user"
        args: list[str] = []
        lines: list[str] = []

        def flush() -> None:
            if lines:
                items.append((role, args, "\n".join(lines).strip()))
                lines.clear()

        for line in content.split("\n"):
            match = _MARKER_RE.match(line.strip())
            word = match.group(1) if match else ""
            if not match or not (word.isupper() or word.lower() in mapping):
                lines.append(line)
                continue
            marker_args = (match.group(2) or "").split()
            flush()
            if word.lower() in mapping:
                role, args = mapping[word.lower()], marker_args
            elif word in _ROLE_MARKERS:
                role, args = _ROLE_MARKERS[word], marker_args
            elif word == _PLACEHOLDER_MARKER:
                if not marker_args:
                    raise ValidationError(
                        "A [PLACEHOLDER] marker needs a name: [PLACEHOLDER history]",
                        field="placeholder",
                        value=line.strip(),
                    )
                items.append((_PLACEHOLDER_MARKER, marker_args[0]))
            else:
                raise ValidationError(
                    f"Unknown role marker [{word}]. Valid roles: {', '.join(VALID_ROLES)} "
                    "(or [PLACEHOLDER name])",
                    field="role",
                    value=word,
                )
        flush()
        return items

    # ------------------------------------------------------------------------------------------
    # Helpers: examples
    # ------------------------------------------------------------------------------------------

    def _forget_examples(self, template_name: str) -> None:
        self._example_cache.pop(template_name, None)
        self._example_vectors.pop(template_name, None)

    def _examples_text(self, template_name: str, variables: Mapping[str, Any]) -> str:
        """The formatted examples; cached when the selection is fixed."""
        config = self._example_selectors.get(template_name, {})
        if config.get("type", "fixed") != "fixed":
            return self._format_examples(
                template_name, self._select_examples(template_name, variables)
            )
        cached = self._example_cache.get(template_name)
        if cached is not None:
            self._example_cache.move_to_end(template_name)
            return cached
        text = self._format_examples(template_name, self._select_examples(template_name, variables))
        if self._max_cached_examples > 0:
            self._example_cache[template_name] = text
            while len(self._example_cache) > self._max_cached_examples:
                self._example_cache.popitem(last=False)
        return text

    def _select_examples(
        self, template_name: str, variables: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Select at most ``max_examples`` examples (default ``DEFAULT_MAX_EXAMPLES``)."""
        examples = self._examples.get(template_name, [])
        if not examples:
            return []
        config = self._example_selectors.get(template_name, {})
        limit = config.get("max_examples", DEFAULT_MAX_EXAMPLES)
        kind = config.get("type", "fixed")
        if kind == "random":
            return random.sample(examples, min(len(examples), limit))
        if kind == "semantic":
            return self._select_semantic(template_name, examples, config, variables, limit)
        return examples[:limit]

    def _select_semantic(
        self,
        template_name: str,
        examples: list[dict[str, Any]],
        config: Mapping[str, Any],
        variables: Mapping[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        """The ``limit`` examples most similar (cosine) to the query; ties keep their order."""
        embedder: Callable[[str], Sequence[float]] = config["embedder"]
        input_key = config.get("input_key")
        if input_key is None:
            input_key = (
                "input"
                if isinstance(variables.get("input"), str)
                else next((k for k, v in variables.items() if isinstance(v, str) and v), None)
            )
        query = variables.get(input_key) if input_key is not None else None
        if not isinstance(query, str) or not query:
            return examples[:limit]
        vectors = self._example_vectors.get(template_name)
        if vectors is None:
            example_key = config.get("example_key") or input_key
            vectors = [
                [float(x) for x in embedder(_example_text(ex, example_key))] for ex in examples
            ]
            self._example_vectors[template_name] = vectors
        query_vector = [float(x) for x in embedder(query)]
        scores = [_cosine(query_vector, vector) for vector in vectors]
        order = sorted(range(len(examples)), key=lambda i: -scores[i])
        return [examples[i] for i in order[:limit]]

    def _format_examples(self, template_name: str, examples: list[dict[str, Any]]) -> str:
        """Write each example with the example template, or from its own keys."""
        if not examples:
            return ""
        entry = self._example_entries.get(template_name)
        formatted: list[str] = []
        for index, ex in enumerate(examples):
            if entry is None:
                formatted.append(_keys_text(ex))
                continue
            missing = [key for key in entry.required if key not in ex]
            if missing:  # added after add_examples checked them (the list is the caller's)
                raise ValidationError(
                    f"Example {index} of template '{template_name}' lacks "
                    f"{', '.join(repr(k) for k in missing)}, read by the example template",
                    field="examples",
                    value=missing,
                    template=template_name,
                    example=index,
                    missing=missing,
                )
            try:
                if entry.compiled is not None:
                    formatted.append(entry.compiled.render(ex, self._custom_filters))
                else:
                    formatted.append(self._example_templates[template_name].format_map(ex))
            except (KeyError, IndexError, AttributeError) as e:
                raise ValidationError(
                    f"Example {index} of template '{template_name}' could not be written: {e!r}",
                    field="examples",
                    value=index,
                    template=template_name,
                    example=index,
                ) from e
        return "\n\n".join(formatted) + "\n\n" if formatted else ""

    def _insert_example_messages(
        self, template_name: str, messages: list[SkyeMessage], variables: Mapping[str, Any]
    ) -> None:
        """Insert the selected examples as user/assistant pairs before the last user message."""
        turns: list[SkyeMessage] = []
        for index, example in enumerate(self._select_examples(template_name, variables)):
            user, assistant = _example_turns(template_name, index, example)
            turns.append(UserMessage(content=user))
            turns.append(AssistantMessage(content=assistant))
        if not turns:
            return
        at = next(
            (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "user"),
            len(messages),
        )
        messages[at:at] = turns

    # ------------------------------------------------------------------------------------------
    # Helpers: content
    # ------------------------------------------------------------------------------------------

    def _apply_content(
        self, template_name: str, messages: list[SkyeMessage], variables: Mapping[str, Any]
    ) -> None:
        """Attach the configured images to the last user message; record the content types."""
        config = self._content_configs.get(template_name)
        if not config:
            return
        images: list[Any] = []
        for variable, content_type in config.items():
            kind, _, fmt = content_type.partition(":")
            value = variables.get(variable)
            if kind != "image" or value is None or value == "":
                continue
            values = value if isinstance(value, list | tuple) else [value]
            images.extend(_load_image(v, fmt or "url", variable) for v in values)
        if images:
            target = next((m for m in reversed(messages) if isinstance(m, UserMessage)), None)
            if target is None:
                target = UserMessage(content="")
                messages.append(target)
            target.images.extend(images)
        for message in messages:
            message.metadata["content_types"] = dict(config)


# ----------------------------------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------------------------------


def _substitute(value: Any) -> Any:
    """``${VAR}`` substitution for configuration values (text, lists, dictionaries)."""
    if isinstance(value, str | list | dict):
        return substitute_env_vars(value)
    return value


def _looks_like_skye(text: str) -> bool:
    """True when the first line that is not blank or a comment starts with ``prompt "``, ``include "`` or ``from "`` (a front
    matter between two ``---`` lines at the top is skipped).
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            lines = lines[end + 1 :]
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        return stripped.startswith(('prompt "', 'include "', 'from "'))
    return False


def _compile_skye(
    name: str,
    text: str,
    filename: str | None,
    resolver: Resolver | None = None,
    key: str | None = None,
) -> _TemplateEntry:
    """Build a ``.skye`` text and keep the prompt ``name`` (or the only one); ``resolver`` reads its includes."""
    from skye.base.dsl import build

    document = build(text, filename=filename, resolver=resolver, key=key)
    if document.diagnostics:
        lines = [d.format() for d in document.diagnostics]
        if resolver is None and any("no resolver was given" in line for line in lines):
            lines.append("register_template takes resolver=, and reads a file path with the folder of the file as its root.")
        raise ValidationError(
            f"Invalid .skye prompt '{name}':\n" + "\n".join(lines),
            field="template",
            value=name,
            diagnostics=lines,
        )
    try:
        spec = document.prompt(name)
    except KeyError:
        try:
            spec = document.prompt()
        except KeyError as e:
            raise ValidationError(
                f"Invalid .skye prompt '{name}': {e.args[0] if e.args else e}",
                field="template",
                value=name,
            ) from e
    allowed = set(spec.allow_missing)
    variables = tuple(v.name for v in spec.variables)
    required = tuple(v.name for v in spec.variables if v.required and v.name not in allowed)
    return _TemplateEntry("skye", variables, required, None, spec)


def _spec_placeholders(parts: Iterable[Any]) -> list[str]:
    """The placeholder names of a prompt spec, in order."""
    names: list[str] = []
    for part in parts:
        if part.kind == "placeholder" and part.name:
            names.append(part.name)
        names.extend(_spec_placeholders(part.children))
    return names


def _simple_fields(text: str) -> tuple[str, ...]:
    """Root names of the ``{name}`` fields of a ``str.format`` text, in first-seen order.

    Raises:
        ValueError: For unmatched braces or a positional field (``{}``, ``{0}``).
    """
    names: dict[str, None] = {}
    for _, field_name, spec, _ in string.Formatter().parse(text):
        if field_name is None:
            continue
        root = re.split(r"[.\[]", field_name, maxsplit=1)[0]
        if not root or root.isdigit():
            raise ValueError("positional fields are not supported; name every field")
        names.setdefault(root, None)
        if spec and "{" in spec:
            for nested in _simple_fields(spec):
                names.setdefault(nested, None)
    return tuple(names)


def _brace_message(message: str) -> str:
    """Name the brace mistake in the words of the former brace check."""
    if any(m in message for m in ("expected '}'", "Single '{'", "end of string", "unmatched '{'")):
        return f"Unmatched opening brace ({message})"
    if "Single '}'" in message:
        return f"Unmatched closing brace ({message})"
    return message


def _validation(
    valid: bool,
    errors: list[str],
    warnings: list[str] | None = None,
    variables: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings or [],
        "variables_found": variables or [],
    }


def _check_role(role: Any, where: str) -> None:
    if role not in VALID_ROLES:
        raise ValidationError(
            f"Invalid role '{role}' for '{where}'. Valid roles: {', '.join(VALID_ROLES)}",
            field="role",
            value=role,
        )


def _make_message(role: str, args: Sequence[str], text: str) -> SkyeMessage:
    """One message of ``role``; a capability message takes its name and call id from ``args``."""
    if role == "system":
        return SystemMessage(content=text)
    if role == "assistant":
        return AssistantMessage(content=text)
    if role == "capability":
        if len(args) < 2:
            raise ValidationError(
                "A capability section needs a name and a call id: [CAPABILITY name call_id]",
                field="role",
                value=" ".join(args),
            )
        return CapabilityMessage(content=text, capability_name=args[0], capability_id=args[1])
    return UserMessage(content=text)


def _to_json(value: Any) -> str:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _check_image_format(image_format: str, variable: str) -> None:
    if image_format not in IMAGE_FORMATS:
        raise ValidationError(
            f"Unsupported image format '{image_format}' for '{variable}'. "
            f"Supported formats: {', '.join(IMAGE_FORMATS)}",
            field=variable,
            value=image_format,
        )


def _load_image(value: Any, image_format: str, variable: str) -> Any:
    """Check one image of the declared format: a URL text, bytes from base64, or a ``Path``."""

    def invalid(reason: str) -> ValidationError:
        return ValidationError(
            f"Invalid image for '{variable}' (format '{image_format}'): {reason}. "
            f"Supported formats: {', '.join(IMAGE_FORMATS)}",
            field=variable,
            value=str(value)[:100],
        )

    if image_format == "url":
        if isinstance(value, str) and value.startswith(("http://", "https://", "data:")):
            return value
        raise invalid("expected an http(s) URL or a data: URI")
    if image_format == "base64":
        if isinstance(value, bytes):
            return value
        if isinstance(value, str) and value.startswith("data:"):
            return value
        if not isinstance(value, str):
            raise invalid("expected base64 text")
        try:
            return base64.b64decode("".join(value.split()), validate=True)
        except (binascii.Error, ValueError) as e:
            raise invalid("the text is not valid base64") from e
    if not isinstance(value, str | Path):
        raise invalid("expected a file path")
    path = Path(value)
    if not path.is_file():
        raise invalid(f"no file at {path}")
    return path


def _value_text(value: Any) -> str:
    """A value of an example as text: JSON for a list or a map, ``str`` otherwise."""
    if isinstance(value, Mapping | list | tuple):
        return _to_json(value)
    return str(value)


def _keys_text(example: Mapping[str, Any]) -> str:
    """One ``Key: value`` line per key, in order (``user_query`` gives ``User query``)."""
    lines = []
    for key, value in example.items():
        label = str(key).replace("_", " ")
        lines.append(f"{label[:1].upper()}{label[1:]}: {_value_text(value)}")
    return "\n".join(lines)


# decision D79
def _example_turns(template_name: str, index: int, example: Mapping[str, Any]) -> tuple[str, str]:
    """The user and the assistant text of an example given as messages."""
    if "input" in example and "output" in example:
        return _value_text(example["input"]), _value_text(example["output"])
    keys = list(example)
    if len(keys) < 2:
        raise ValidationError(
            f"add_examples(as_messages=True): example {index} of template '{template_name}' "
            "needs two keys (input and output, or a first key for the user and a last key for "
            "the assistant)",
            field="examples",
            value=keys,
            template=template_name,
            example=index,
        )
    return _value_text(example[keys[0]]), _value_text(example[keys[-1]])


def _example_text(example: Mapping[str, Any], key: str | None) -> str:
    for candidate in (key, "input"):
        if candidate is not None and candidate in example:
            return str(example[candidate])
    return " ".join(str(v) for v in example.values() if isinstance(v, str))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# -- output schema -----------------------------------------------------------------------------


def _dataclass_schema(cls: type, seen: set[type]) -> dict[str, Any]:
    """JSON schema of a dataclass (nested dataclasses, lists, optionals, literals)."""
    if cls in seen:
        return {"type": "object", "title": cls.__name__}
    seen = seen | {cls}
    hints = get_type_hints(cls)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in dataclasses.fields(cls):
        tp = hints.get(f.name, Any)
        sub = _type_schema(tp, seen)
        description = f.metadata.get("description") if f.metadata else None
        if description:
            sub = {**sub, "description": str(description)}
        properties[f.name] = sub
        has_default = (
            f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        )
        if not has_default and not _is_optional(tp):
            required.append(f.name)
    schema: dict[str, Any] = {"title": cls.__name__, "type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _is_optional(tp: Any) -> bool:
    return get_origin(tp) in (Union, types.UnionType) and type(None) in get_args(tp)


def _type_schema(tp: Any, seen: set[type]) -> dict[str, Any]:
    if tp is Any:
        return {}
    if tp is type(None) or tp is None:
        return {"type": "null"}
    origin = get_origin(tp)
    args = get_args(tp)
    if origin in (Union, types.UnionType):
        options = [a for a in args if a is not type(None)]
        if len(options) == 1:
            return _type_schema(options[0], seen)
        return {"anyOf": [_type_schema(a, seen) for a in options]}
    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        kinds = {_PRIMITIVES.get(type(v)) for v in values}
        if len(kinds) == 1 and None not in kinds:
            schema["type"] = kinds.pop()
        return schema
    if origin in (list, tuple, set, frozenset) or (
        isinstance(origin, type) and issubclass(origin, Sequence) and origin is not str
    ):
        return {"type": "array", "items": _type_schema(args[0], seen) if args else {}}
    if origin is dict or (isinstance(origin, type) and issubclass(origin, Mapping)):
        schema = {"type": "object"}
        if len(args) == 2:
            schema["additionalProperties"] = _type_schema(args[1], seen)
        return schema
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return _dataclass_schema(tp, seen)
    if isinstance(tp, type):
        for base, name in _PRIMITIVES.items():
            if issubclass(tp, base):
                return {"type": name}
    return {}


# ``bool`` before ``int``: a bool is an int in Python.
_PRIMITIVES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
    list: "array",
    tuple: "array",
    dict: "object",
}


def _check_json_schema(schema: Any, where: str) -> None:
    """Check the shape of a JSON-schema dictionary (``type`` or ``properties``)."""
    if not isinstance(schema, Mapping):
        raise ValidationError(
            f"Invalid output schema at '{where}': expected a dictionary", field=where, value=schema
        )
    if "type" not in schema and "properties" not in schema:
        raise ValidationError(
            f"Invalid output schema at '{where}': a JSON schema needs 'type' or 'properties'",
            field=where,
            value=dict(schema),
        )
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind] if kind is not None else []
    for k in kinds:
        if k not in _JSON_TYPES:
            raise ValidationError(
                f"Invalid output schema at '{where}': unknown type {k!r}. "
                f"Valid types: {', '.join(sorted(_JSON_TYPES))}",
                field=where,
                value=k,
            )
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise ValidationError(
                f"Invalid output schema at '{where}': 'properties' must be a dictionary",
                field=where,
                value=properties,
            )
        for name, sub in properties.items():
            if not isinstance(sub, Mapping):
                raise ValidationError(
                    f"Invalid output schema at '{where}.{name}': expected a dictionary",
                    field=f"{where}.{name}",
                    value=sub,
                )
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list) or not all(isinstance(r, str) for r in required)
    ):
        raise ValidationError(
            f"Invalid output schema at '{where}': 'required' must be a list of names",
            field=where,
            value=required,
        )


def _schema_fields(
    schema: Mapping[str, Any], prefix: str, parent_required: bool
) -> Iterable[tuple[str, Mapping[str, Any], bool]]:
    """Every field of an object schema as ``(path, schema, required)``, nested ones included."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    required = set(schema.get("required") or [])
    for name, sub in properties.items():
        if not isinstance(sub, Mapping):
            continue
        path = f"{prefix}{name}"
        is_required = parent_required and name in required
        yield path, sub, is_required
        yield from _schema_fields(sub, f"{path}.", is_required)
        items = sub.get("items")
        if isinstance(items, Mapping):
            yield from _schema_fields(items, f"{path}[].", is_required)


def _type_label(schema: Mapping[str, Any]) -> str:
    if "enum" in schema:
        return "one of " + ", ".join(json.dumps(v) for v in schema["enum"])
    kind = schema.get("type")
    if kind == "array" and isinstance(schema.get("items"), Mapping):
        return f"array of {_type_label(schema['items'])}"
    if isinstance(kind, list):
        return " or ".join(str(k) for k in kind)
    if "anyOf" in schema:
        return " or ".join(_type_label(s) for s in schema["anyOf"])
    return str(kind) if kind else "any"
