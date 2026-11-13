"""The partials of the bundled catalogue (task 25.4, Requirement 63).

A bundled template may include a partial that lives in a subfolder of the catalogue. The catalogue
resolver reads it from the folder of a source checkout or from ``templates.zip``; the cache of the
compiled template changes when a partial changes; a user file cannot reach the catalogue. The
templates here are synthetic: no real template is migrated.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from skye.base.dsl.cache import build_cached, cache_info, clear_cache
from skye.dsl import build
from skye.prompts import BasePromptBuilder, loaders, messages
from tests.budget import measure

ROOT = measure.ROOT

MEMORY = """---
partial = true
---
prompt "memory" {
  variables = {
    note = list({ content = string "The note" }, []) "Notes"
  }
  message "system" {
    when note { text = "Notes: {{ note }}" }
  }
}
"""

TOOL = """---
version = "1.0"
---
include "common/memory.skye" as memory

prompt "tool" {
  variables = {
    use memory
    input = string("") "The user's message"
  }
  message "system" {
    use memory
    text = "Answer."
  }
}
"""

EXPANDED = """---
version = "1.0"
---
prompt "tool" {
  variables = {
    note = list({ content = string "The note" }, []) "Notes"
    input = string("") "The user's message"
  }
  message "system" {
    when note { text = "Notes: {{ note }}" }
    text = "Answer."
  }
}
"""


def _hook():
    spec = importlib.util.spec_from_file_location(
        "hatch_build", ROOT / "scripts" / "hatch_build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render(builder: BasePromptBuilder) -> list[tuple[str, str]]:
    messages_ = builder.render("tool", {"note": [{"content": "a"}], "input": "hi"})
    return [(m.role, m.content) for m in messages_]


@pytest.fixture
def folder(tmp_path, monkeypatch) -> Path:
    """A source checkout: loose files, the partial in a subfolder."""
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "memory.skye").write_text(MEMORY, encoding="utf-8")
    (tmp_path / "tool.skye").write_text(TOOL, encoding="utf-8")
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", tmp_path / "none.zip")
    monkeypatch.setattr(messages, "_BUNDLED_ENTRIES", {})
    return tmp_path


@pytest.fixture
def archive(tmp_path, monkeypatch) -> Path:
    """An installed wheel: no loose file, the partial is a member with its relative path."""
    empty = tmp_path / "templates"
    empty.mkdir()
    path = tmp_path / "templates.zip"
    path.write_bytes(
        _hook().pack_templates({"tool.skye": TOOL.encode(), "common/memory.skye": MEMORY.encode()})
    )
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", empty)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", path)
    monkeypatch.setattr(loaders, "_archive_index", None)
    monkeypatch.setattr(messages, "_BUNDLED_ENTRIES", {})
    return path


def _expected() -> list[tuple[str, str]]:
    builder = BasePromptBuilder.__new__(BasePromptBuilder)
    BasePromptBuilder.__init__(builder)
    builder.register_template("tool", EXPANDED, version="1.0", from_string=True)
    return _render(builder)


def test_a_partial_is_not_a_template(folder) -> None:
    assert loaders.bundled_names() == ["tool"]
    assert list(loaders.discover_templates(folder)) == ["tool"]


def test_the_folder_gives_the_same_messages_as_the_expanded_text(folder) -> None:
    assert _render(BasePromptBuilder()) == _expected()


def test_the_archive_gives_the_same_messages_as_the_folder(archive) -> None:
    assert loaders.bundled_names() == ["tool"]  # the partial is a member, not a template
    assert _render(BasePromptBuilder()) == _expected()


def test_the_archive_and_the_folder_build_equal_objects(folder, archive) -> None:
    resolver = loaders.catalogue_resolver
    from_archive = build(TOOL, resolver=resolver, key="tool.skye")
    from_expanded = build(EXPANDED)
    assert not from_archive.diagnostics
    assert [(v.name, v.type) for v in from_archive.prompt("tool").variables] == [
        (v.name, v.type) for v in from_expanded.prompt("tool").variables
    ]


def test_a_changed_partial_gives_a_new_compile(folder) -> None:
    first = _render(BasePromptBuilder())
    partial = folder / "common" / "memory.skye"
    partial.write_text(MEMORY.replace("Notes: ", "Changed: "), encoding="utf-8")
    second = _render(BasePromptBuilder())  # same process: the compiled entry must not be served
    assert first != second and "Changed" in second[0][1]


def test_the_fingerprint_changes_with_a_partial_and_not_without_one(folder) -> None:
    resolver = loaders.catalogue_resolver
    before = resolver.fingerprint()
    assert resolver.fingerprint() == before
    (folder / "common" / "memory.skye").write_text(MEMORY + "\n\n", encoding="utf-8")
    assert resolver.fingerprint() != before


def test_the_archive_fingerprint_is_its_stamp(archive) -> None:
    assert loaders.catalogue_resolver.fingerprint() == loaders._archive()[0]


@pytest.mark.parametrize("target", ["../x.skye", "../../etc/passwd", "common/../../x.skye"])
def test_a_path_above_the_catalogue_is_refused(folder, target) -> None:
    with pytest.raises(ValueError):
        loaders.catalogue_resolver(target, "tool.skye")


def test_a_missing_file_names_the_catalogue(folder) -> None:
    with pytest.raises(FileNotFoundError) as caught:
        loaders.catalogue_resolver("common/none.skye", "tool.skye")
    assert str(folder) in str(caught.value)


def test_a_path_is_relative_to_the_including_file(folder) -> None:
    found = loaders.catalogue_resolver("memory.skye", "common/other.skye")
    assert found.key == "common/memory.skye" and found.text == MEMORY


def test_a_user_file_cannot_reach_the_catalogue(folder, tmp_path_factory) -> None:
    from skye.utils.skye_files import file_resolver

    mine = tmp_path_factory.mktemp("mine")
    entry = mine / "mine.skye"
    text = 'include "skye:common/memory.skye" as memory\n' + EXPANDED.split("---\n", 2)[2]
    document = build(text, resolver=file_resolver(entry), key=str(entry))
    assert any("not a relative path" in d.format() for d in document.diagnostics)
    document = build(
        'include "common/memory.skye" as memory\nprompt "x" { message "system" { text = "a" } }',
        resolver=file_resolver(entry),
        key=str(entry),
    )
    assert any("no such file" in d.format() for d in document.diagnostics)


def test_a_text_with_an_include_is_cached_only_with_a_fingerprint(folder) -> None:
    clear_cache()
    plain = lambda target, from_key: loaders.catalogue_resolver(target, from_key)  # noqa: E731
    build_cached(TOOL, filename="tool.skye", resolver=plain, key="tool.skye")
    build_cached(TOOL, filename="tool.skye", resolver=plain, key="tool.skye")
    assert cache_info().size == 0 and cache_info().hits == 0  # no fingerprint: built every time
    resolver = loaders.catalogue_resolver
    build_cached(TOOL, filename="tool.skye", resolver=resolver, key="tool.skye")
    build_cached(TOOL, filename="tool.skye", resolver=resolver, key="tool.skye")
    assert cache_info().size == 1 and cache_info().hits == 1
    (folder / "common" / "memory.skye").write_text(MEMORY + "\n\n", encoding="utf-8")
    build_cached(TOOL, filename="tool.skye", resolver=resolver, key="tool.skye")
    assert cache_info().size == 2  # the fingerprint changed: a new entry, not the stale one
    clear_cache()


def test_a_text_without_an_include_is_cached_as_before() -> None:
    clear_cache()
    text = 'prompt "a" { message "system" { text = "x" } }'
    build_cached(text)
    build_cached(text)
    assert cache_info().size == 1 and cache_info().hits == 1
    clear_cache()


def test_the_hook_packs_the_partials_with_their_relative_path(folder) -> None:
    hook = _hook()
    source = folder.parent / "src_skye"
    (source / "prompts").mkdir(parents=True)
    (source / "prompts" / "templates").symlink_to(folder, target_is_directory=True)
    found = hook.collect_templates(source, {})
    assert sorted(found) == ["common/memory.skye", "tool.skye"]


def test_the_hook_strips_a_partial_and_keeps_its_front_matter(tmp_path) -> None:
    hook = _hook()
    text = MEMORY.replace("prompt", "# a comment\nprompt", 1)
    source = tmp_path / "skye" / "prompts" / "templates" / "common"
    source.mkdir(parents=True)
    (source / "memory.skye").write_text(text, encoding="utf-8")
    target = tmp_path / "out"
    copies = hook.make_copies(tmp_path / "skye", target)
    copy = next(Path(c) for c, d in copies.items() if d.endswith("common/memory.skye"))
    stripped = copy.read_text(encoding="utf-8")
    assert "# a comment" not in stripped and stripped.startswith("---\npartial = true\n---\n")


def test_building_a_bundled_template_stays_under_the_builder_budget(folder) -> None:
    import time

    BasePromptBuilder()  # warm
    start = time.perf_counter()
    for _ in range(10):
        BasePromptBuilder()
    assert (time.perf_counter() - start) / 10 < 0.01


def test_the_wheel_files_have_the_archive_and_no_loose_partial(tmp_path) -> None:
    """The partials go into the archive with their path; no loose copy is forced into the wheel."""
    hook = _hook()
    source = tmp_path / "skye"
    (source / "prompts" / "templates" / "common").mkdir(parents=True)
    (source / "prompts" / "templates" / "common" / "memory.skye").write_text(
        MEMORY, encoding="utf-8"
    )
    (source / "prompts" / "templates" / "tool.skye").write_text("# c\n" + TOOL, encoding="utf-8")
    files = hook.make_wheel_files(source, tmp_path / "out")
    assert list(files.values()) == ["skye/prompts/templates.zip"]
    import zipfile

    with zipfile.ZipFile(next(iter(files))) as z:
        assert z.namelist() == ["common/memory.skye", "tool.skye"]


def test_the_wheel_excludes_the_partials_of_the_subfolders() -> None:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "src/skye/prompts/templates/**/*.skye" in wheel["exclude"]
