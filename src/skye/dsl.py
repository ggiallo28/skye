# decision D78
# decision D83
"""The `.skye` language: build, check, format, write back, draw (public path of `skye.base.dsl`).

The code lives in `skye.base.dsl` (and `load_document` in `skye.utils.skye_files`);
import from here. These tools work on text and serve every kind of `.skye` file (prompts, routers,
flows): `build` turns a text into a `Document`, `build_cached` does it once per text,
`clear_cache` forgets the cached documents, `to_text` writes a spec or a document back, and
`SkyeSyntaxError` (with `.diagnostics`) is what `Document.raise_for_errors()` raises for a text
with mistakes. Read a file with `skye.load(path)`, or with `load_document(path)` to get the
document and its diagnostics without raising. `describe(spec)` tells what a prompt, router
or flow block takes and gives back (`PromptInfo`, `RouterInfo`, `FlowInfo`).
"""

from skye.base.dsl import (
    Diagnostic,
    FormatError,
    Resolved,
    SkyeSyntaxError,
    build,
    build_cached,
    check_text,
    clear_cache,
    format_text,
    to_mermaid,
    to_text,
)
from skye.base.dsl.info import FlowInfo, PromptInfo, RouterInfo, describe
from skye.utils.skye_files import load_document

__all__ = [
    "Diagnostic",
    "FlowInfo",
    "FormatError",
    "PromptInfo",
    "Resolved",
    "RouterInfo",
    "SkyeSyntaxError",
    "build",
    "build_cached",
    "check_text",
    "clear_cache",
    "describe",
    "format_text",
    "load_document",
    "to_mermaid",
    "to_text",
]
