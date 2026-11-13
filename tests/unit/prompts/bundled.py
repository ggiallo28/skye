"""Read a bundled template from the source folder the way the library does: with its partials.

A template of ``src/skye/prompts/templates`` may ``include`` a partial of ``common/`` (task 24.6),
so the
text alone no longer builds: it needs the resolver of its folder. These two helpers are what a test
used to write as ``load_prompt(path.read_text(), name)`` and ``build(path.read_text())``.
"""

from __future__ import annotations

from pathlib import Path

from skye.base.dsl import PromptSpec
from skye.base.exceptions import ValidationError
from skye.dsl import build
from skye.prompts import BasePromptBuilder
from skye.utils.skye_files import file_resolver


def build_template(path: Path):
    """The built document of the template at ``path``, with its includes resolved in its folder."""
    return build(
        path.read_text(encoding="utf-8"),
        filename=str(path),
        resolver=file_resolver(path),
        key=str(path.resolve()),
    )


def load_template(path: Path, name: str | None = None) -> PromptSpec:
    """One prompt of the template at ``path``; a mistake raises ``ValidationError`` like
    ``load_prompt``."""
    document = build_template(path)
    if document.diagnostics:
        lines = [d.format() for d in document.diagnostics]
        raise ValidationError(
            "Invalid .skye prompt:\n" + "\n".join(lines), field="text", value=name
        )
    return document.prompt(name)


REPO = Path(__file__).resolve().parents[3]
BUNDLED_DIR = REPO / "src" / "skye" / "prompts" / "templates"
GALLERY_DIR = REPO / "examples" / "prompts" / "catalogue"


def template_path(name: str) -> Path:
    """The file of a prompt: the bundled one, or the one of the gallery (D118: most prompts are
    examples)."""
    bundled = BUNDLED_DIR / f"{name}.skye"
    return bundled if bundled.exists() else GALLERY_DIR / f"{name}.skye"


def gallery_builder() -> BasePromptBuilder:
    """A builder with every prompt of the gallery registered from its path (the includes are
    resolved)."""
    builder = BasePromptBuilder()
    for path in sorted(GALLERY_DIR.glob("*.skye")):
        builder.register_template(path.stem, str(path), from_string=False)
    return builder
