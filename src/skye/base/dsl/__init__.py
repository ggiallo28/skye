# decisions D50 to D61, decision D88
"""The ``.skye`` language: parser, checker, expression checker and block models.

The functions take text, never a path: ``base`` does no file I/O. The code that reads a file
(``skye check``, the component that loads a router or a flow) reads the text and calls them.

Entry points:

* :func:`parse` ``(text, filename=None) -> Tree``: the syntax tree; raises :class:`SkyeSyntaxError`
  with every syntax mistake found.
* :func:`build` ``(text_or_tree, *, filename=None, registry_names=None, resolver=None) -> Document``: the validated
  blocks (``RouterSpec``, ``FlowSpec``, ``PromptSpec``) and the list of diagnostics.
* :func:`check_text` ``(text, filename=None, registry_names=None) -> list[Diagnostic]``.
* :func:`block_schema` ``(kind=None) -> dict``: the JSON Schema of the blocks.
* :func:`evaluate` ``(expression, scope)``: a safe evaluator (never ``eval``).
* :func:`skeleton` ``(kind, name=None, template=None) -> str``: a starting ``.skye`` text.
* :func:`format_text` ``(text, filename=None) -> str``: the standard layout, comments kept
  (``skye fmt``).
* :func:`to_mermaid` ``(spec, direction=None) -> str``: a flow or a router as a Mermaid diagram
  (``skye render``).
* :func:`split_metadata` / :func:`format_metadata`: the ``---`` metadata at the top of a file
  (TOML); :func:`build` puts it in ``Document.metadata``.

Codename: stratus.
"""

from skye.base.dsl.build import Document, build, check_text
from skye.base.dsl.cache import CacheInfo, build_cached, cache_info, clear_cache
from skye.base.dsl.emit import to_text
from skye.base.dsl.errors import Diagnostic, SkyeSyntaxError, did_you_mean, suggest
from skye.base.dsl.expressions import (
    ALLOWED_FUNCTIONS,
    Expression,
    SkyeExpressionError,
    check_expression,
    evaluate,
)
from skye.base.dsl.fmt import FormatError, format_text
from skye.base.dsl.include import Resolved
from skye.base.dsl.lexer import Token, tokenize
from skye.base.dsl.mermaid import to_mermaid
from skye.base.dsl.metadata import format_metadata, split_metadata
from skye.base.dsl.parser import parse, parse_collect
from skye.base.dsl.schema import block_schema
from skye.base.dsl.skeletons import TEMPLATES, new_flow, new_prompt, new_router, skeleton
from skye.base.dsl.specs import (
    OUTPUT_FORMATS,
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
    format_duration,
    parse_duration,
)
from skye.base.dsl.tree import Tree

__all__ = [
    "ALLOWED_FUNCTIONS",
    "TEMPLATES",
    "AllowedFailsPolicySpec",
    "BranchSpec",
    "CacheInfo",
    "ChoiceSpec",
    "ContextFieldSpec",
    "ContextSpec",
    "Diagnostic",
    "Document",
    "Expression",
    "FormatError",
    "FlowSpec",
    "OUTPUT_FORMATS",
    "OutputFieldSpec",
    "OutputSpec",
    "ParallelSpec",
    "PromptPartSpec",
    "PromptSpec",
    "Resolved",
    "RetryPolicySpec",
    "RetrySpec",
    "RouteSpec",
    "RouterSpec",
    "SetSpec",
    "SkyeExpressionError",
    "SkyeSyntaxError",
    "StepSpec",
    "TargetSpec",
    "Token",
    "Tree",
    "VariableSpec",
    "block_schema",
    "build",
    "build_cached",
    "cache_info",
    "check_expression",
    "check_text",
    "clear_cache",
    "did_you_mean",
    "evaluate",
    "format_duration",
    "format_text",
    "format_metadata",
    "new_flow",
    "new_prompt",
    "new_router",
    "parse",
    "parse_collect",
    "parse_duration",
    "skeleton",
    "split_metadata",
    "suggest",
    "to_mermaid",
    "to_text",
    "tokenize",
]
