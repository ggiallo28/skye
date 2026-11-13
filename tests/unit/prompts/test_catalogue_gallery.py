"""The gallery `examples/prompts/catalogue/` (task 24.11, D118): prompts to copy, not bundled.

Every file builds with the file resolver of its folder, renders with its sample variables, follows the naming
convention, and the shared parts it includes (`common/`) are the bundled ones byte for byte.
"""

from __future__ import annotations

import json

import pytest

from skye.base.dsl import build
from skye.prompts import BasePromptBuilder
from skye.utils.skye_files import file_resolver
from tests.unit.prompts.bundled import BUNDLED_DIR, GALLERY_DIR
from tests.unit.prompts.test_template_names import AGENTS, PATTERN

FILES = sorted(GALLERY_DIR.glob("*.skye"))
IDS = [p.stem for p in FILES]


def _samples(stem: str) -> list[dict]:
    """The variables of every render of a prompt: `stem.json` and any `stem.<part>.json`, an object or a list."""
    files = sorted(GALLERY_DIR.glob(f"{stem}.json")) + sorted(GALLERY_DIR.glob(f"{stem}.*.json"))
    renders: list[dict] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        renders += data if isinstance(data, list) else [data]
    return renders


def test_the_gallery_holds_the_prompts_that_are_not_bundled():
    assert len(FILES) == 27
    assert not {p.stem for p in FILES} & {p.stem for p in BUNDLED_DIR.glob("*.skye")}


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_a_gallery_file_builds_with_its_folder_as_root(path):
    document = build(
        path.read_text(encoding="utf-8"),
        filename=str(path),
        resolver=file_resolver(path),
        key=str(path.resolve()),
    )
    assert document.diagnostics == [], [d.format() for d in document.diagnostics]
    assert document.prompt(path.stem)


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_a_gallery_file_renders_with_its_samples(path):
    builder = BasePromptBuilder()
    builder.register_template(path.stem, str(path), from_string=False)
    samples = _samples(path.stem)
    assert samples, f"{path.stem} has no sample file"
    for variables in samples:
        assert builder.render(path.stem, variables)


def test_every_sample_file_belongs_to_a_gallery_file():
    stems = {p.stem for p in FILES}
    orphans = [
        p.name for p in GALLERY_DIR.glob("*.json") if p.name.split(".")[0] not in stems
    ]
    assert orphans == []


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_a_gallery_name_follows_the_convention(path):
    assert PATTERN.match(path.stem), path.stem
    assert (path.stem in AGENTS) == path.stem.startswith("agent_") or path.stem == "extraction_generic"
    assert f'prompt "{path.stem}"' in path.read_text(encoding="utf-8")


def test_the_gallery_copy_of_the_shared_parts_is_the_bundled_one():
    bundled = sorted((BUNDLED_DIR / "common").glob("*.skye"))
    gallery = sorted((GALLERY_DIR / "common").glob("*.skye"))
    assert [p.name for p in gallery] == [p.name for p in bundled]
    for one, other in zip(bundled, gallery, strict=True):
        assert one.read_bytes() == other.read_bytes(), f"{other.name} drifted from the bundled copy"
