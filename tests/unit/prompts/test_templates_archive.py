"""The bundled templates come from the folder of a source checkout or from the archive of a wheel (task 24.7).

A source checkout keeps the loose `.skye` files in `skye/prompts/templates`. An installed wheel keeps one
`templates.zip` that `hatch_build.py` made, and the loader reads it by name. Both give the same templates.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from skye.base.exceptions import ValidationError
from skye.dsl import build
from skye.prompts import BasePromptBuilder, loaders
from skye.prompts.skye_prompts import render_prompt
from tests.budget import measure
from tests.unit.prompts.bundled import build_template

ROOT = measure.ROOT
SOURCE = ROOT / "src" / "skye" / "prompts" / "templates"
NAMES = ("text_classification", "text_explanation", "text_summarization")
PARTIALS = sorted((SOURCE / "common").glob("*.skye"))


def _hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hatch_build", ROOT / "scripts" / "hatch_build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def archive(tmp_path, monkeypatch) -> Path:
    """An installed wheel: no loose file in the folder, and `templates.zip` made with the packing of the build hook."""
    templates = {f"{name}.skye": (SOURCE / f"{name}.skye").read_bytes() for name in NAMES}
    templates.update({f"common/{p.name}": p.read_bytes() for p in PARTIALS})
    empty = tmp_path / "templates"
    empty.mkdir()
    path = tmp_path / "templates.zip"
    path.write_bytes(_hook().pack_templates(templates))
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", empty)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", path)
    monkeypatch.setattr(loaders, "_archive_index", None)
    return path


def test_a_source_checkout_reads_the_folder() -> None:
    assert loaders._folder_has_templates()
    names = loaders.bundled_names()
    assert len(names) == 11 and names == sorted(names)
    assert loaders.read_bundled("text_summarization") == (SOURCE / "text_summarization.skye").read_text(encoding="utf-8")
    assert loaders.bundled_origin("text_summarization") == str(SOURCE / "text_summarization.skye")


def test_a_wheel_reads_the_archive(archive) -> None:
    assert not loaders._folder_has_templates()
    assert loaders.bundled_names() == sorted(NAMES)
    assert loaders.read_bundled("text_summarization") == (SOURCE / "text_summarization.skye").read_text(encoding="utf-8")
    assert loaders.bundled_origin("text_summarization") == f"{archive}/text_summarization.skye"


def test_a_missing_entry_names_the_template(archive) -> None:
    with pytest.raises(FileNotFoundError) as caught:
        loaders.read_bundled("no-such-prompt")
    assert "no-such-prompt" in str(caught.value) and str(archive) in str(caught.value)


def test_a_folder_without_the_template_names_it(monkeypatch) -> None:
    with pytest.raises(FileNotFoundError) as caught:
        loaders.read_bundled("no-such-prompt")
    assert "no-such-prompt" in str(caught.value)


def test_an_unreadable_archive_is_a_clear_error(archive) -> None:
    archive.write_bytes(b"this is not a zip file")
    with pytest.raises(ValidationError) as caught:
        loaders.bundled_names()
    assert str(archive) in str(caught.value)
    with pytest.raises(ValidationError):
        loaders.load_default_templates(BasePromptBuilder.__new__(BasePromptBuilder))


def test_no_folder_and_no_archive_registers_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", tmp_path / "none")
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", tmp_path / "none.zip")
    assert loaders.bundled_names() == []
    assert loaders.load_default_templates(object()) == 0


def test_a_builder_registers_the_archive_and_compiles_at_the_first_use(
    archive, monkeypatch
) -> None:
    import skye.prompts.messages as messages

    calls: list[str] = []
    real = messages._compile_skye
    monkeypatch.setattr(
        messages, "_compile_skye", lambda *a, **k: calls.append(a[0]) or real(*a, **k)
    )
    monkeypatch.setattr(messages, "_BUNDLED_ENTRIES", {})
    builder = BasePromptBuilder()
    assert calls == []  # registered, not compiled
    assert builder.get_template("text_summarization") == (SOURCE / "text_summarization.skye").read_text(encoding="utf-8")
    assert calls == []  # the text is there with no compile
    assert builder.render("text_summarization", {"text": "hi"})
    assert calls == ["text_summarization"]


def test_a_template_of_the_archive_builds_to_the_objects_of_the_file(archive) -> None:
    for name in NAMES:
        from_archive = build(loaders.read_bundled(name), resolver=loaders.catalogue_resolver, key=name)
        from_file = build_template(SOURCE / f"{name}.skye")
        values = json.loads((ROOT / "examples" / "prompts" / "bundled" / f"{name}.json").read_text(encoding="utf-8"))
        archive_messages = render_prompt(from_archive.prompt(name), values)
        assert [(m.role, m.content) for m in archive_messages] == [
            (m.role, m.content) for m in render_prompt(from_file.prompt(name), values)
        ]


def test_the_archive_and_the_folder_render_the_same_messages(archive, monkeypatch) -> None:
    values = {"text": "hello", "style": "formal"}
    from_archive = [(m.role, m.content) for m in BasePromptBuilder().render("text_summarization", values)]
    monkeypatch.undo()
    from_folder = [(m.role, m.content) for m in BasePromptBuilder().render("text_summarization", values)]
    assert from_archive == from_folder


def test_the_error_of_a_broken_entry_names_the_template_at_its_first_use(
    tmp_path, monkeypatch
) -> None:
    """A template that does not compile fails when it is used, with its name, as a file of the folder does."""
    broken = tmp_path / "templates.zip"
    broken.write_bytes(
        _hook().pack_templates({"broken.skye": b'prompt "broken" {\n  message "system" {'})
    )
    empty = tmp_path / "t"
    empty.mkdir()
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", empty)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", broken)
    monkeypatch.setattr(loaders, "_archive_index", None)
    builder = BasePromptBuilder()  # no error here
    with pytest.raises(ValidationError) as caught:
        builder.render("broken", {})
    assert "broken" in str(caught.value)


def test_the_archive_is_read_once_for_the_process_and_by_threads(archive, monkeypatch) -> None:
    opened = []
    real = zipfile.ZipFile

    class Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            opened.append(args[0])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(loaders.zipfile, "ZipFile", Counting)
    results = []

    def read() -> None:
        results.append(loaders.bundled_names())

    threads = [threading.Thread(target=read) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(r == sorted(NAMES) for r in results) and len(results) == 8
    BasePromptBuilder()
    BasePromptBuilder()
    assert len(opened) == 1


def test_a_changed_archive_is_read_again(archive) -> None:
    assert loaders.bundled_names() == sorted(NAMES)
    archive.write_bytes(
        _hook().pack_templates(
            {"text_summarization.skye": (SOURCE / "text_summarization.skye").read_bytes(), **{f"common/{p.name}": p.read_bytes() for p in PARTIALS}}
        )
    )
    assert loaders.bundled_names() == ["text_summarization"]


def test_the_packing_is_the_same_bytes_every_time_and_sorted() -> None:
    hook = _hook()
    templates = {"b.skye": b"b", "a.skye": b"a" * 100}
    first = hook.pack_templates(templates)
    assert first == hook.pack_templates(dict(reversed(list(templates.items()))))
    import io

    with zipfile.ZipFile(io.BytesIO(first)) as z:
        assert z.namelist() == ["a.skye", "b.skye"]
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert {i.compress_type for i in z.infolist()} == {zipfile.ZIP_DEFLATED}


def test_a_user_folder_still_reads_a_real_directory(tmp_path, archive) -> None:
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "mine.skye").write_text('prompt "mine" { message "user" { text = "hi" } }\n', encoding="utf-8")
    builder = BasePromptBuilder.__new__(BasePromptBuilder)
    registered = []

    class Collector:
        def register_bundled_template(self, name, text, path, version="1.0", stamp=None):
            registered.append((name, str(path)))

        def register_template(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("a .skye file is registered as a bundled template")

    assert loaders.load_default_templates(Collector(), folder) == 1
    assert registered[0][0] == "mine" and registered[0][1].startswith(str(folder))
    assert builder is not None
