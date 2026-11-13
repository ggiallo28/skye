# decision D76
"""Prompt templates rendered into role-based messages.

Part of the base install (``pip install skyeai``): the template engine is the standard
library's, with ``{{ var }}`` interpolation and filters, and no Jinja2. Text templates do
interpolation only; conditions and loops are written in ``.skye`` prompts
(``when``, ``each``).

Key features:
- Template registration, versioning and composition
- Default values, optional variables and partial builders
- Few-shot examples with an example selector, as text or as user/assistant messages
- Roles from ``[SYSTEM]``, ``[USER]`` and ``[ASSISTANT]`` markers
- Output instructions from a declared schema, as JSON, a Markdown table or XML
- Bundled templates (``text_classification``, ``extraction_structured``, ``text_summarization``, ...)
- ``.skye`` prompt blocks rendered with real roles (``load_prompt``, ``render_prompt``)
- A rendered prompt as provider-agnostic parts for a native call (``render_parts`` gives a
  ``PromptParts``; ``output_json_schema`` the JSON Schema of the ``output`` block)
- Help for a prompt: its inputs and output (``describe_prompt``, ``prompt_help``,
  ``BasePromptBuilder.help``, ``skye prompt info``)

The specs a ``.skye`` prompt is read into (``PromptSpec``, its ``PromptPartSpec`` parts and its
``OutputSpec`` output block) are exported here too.

Example:
    >>> from skye.prompts import BasePromptBuilder
    >>> builder = BasePromptBuilder()
    >>> builder.register_template("greeting", "Hello {{ name }}!")
    >>> messages = builder.render("greeting", {"name": "Alice"})
    >>> messages[0].content
    'Hello Alice!'

Codename: cirrus.
"""

from skye.base.lazy_import import lazy_names as _lazy_names
from skye.base.dsl import OutputSpec, PromptPartSpec, PromptSpec
from skye.base.dsl.info import (
    InputInfo,
    OutputFieldInfo,
    OutputInfo,
    PromptInfo,
    describe_prompt,
    prompt_help,
)
from skye.base.interfaces.prompt import PromptBuilderInterface
from skye.base.prompt_parts import OutputSchema, PromptParts

from .messages import BasePromptBuilder
from .skye_prompts import (
    PromptRunnable,
    active_output,
    load_prompt,
    output_instructions,
    output_json_schema,
    render_parts,
    render_prompt,
)

# The offline check is read at first use, so importing the package does not import it.
_LAZY = {"check_template_filter": "conformance"}
__getattr__ = _lazy_names(__name__, _LAZY)

__all__ = [
    *_LAZY,
    "PromptBuilderInterface",
    "BasePromptBuilder",
    "InputInfo",
    "OutputFieldInfo",
    "OutputInfo",
    "OutputSchema",
    "OutputSpec",
    "PromptInfo",
    "PromptPartSpec",
    "PromptParts",
    "PromptRunnable",
    "PromptSpec",
    "describe_prompt",
    "prompt_help",
    "active_output",
    "load_prompt",
    "output_instructions",
    "output_json_schema",
    "render_parts",
    "render_prompt",
]
