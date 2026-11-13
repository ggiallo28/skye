"""The bundled templates are compiled at their first use, once for the process, and without the validation of their objects (task 24.8)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

import skye.prompts.messages as messages
from skye.base.exceptions import ValidationError
from skye.base.validated import trusted
from skye.dsl import build
from skye.utils.skye_files import file_resolver
from skye.prompts import BasePromptBuilder
from skye.prompts import loaders
from skye.prompts.loaders import TEMPLATES_DIR, load_default_templates

pytestmark = pytest.mark.skipif(
    not loaders._folder_has_templates(),
    reason="reads the loose templates of a source checkout; an installed wheel keeps them in an archive",
)
BUNDLED = sorted(TEMPLATES_DIR.glob("*.skye"))


@pytest.fixture(autouse=True)
def empty_process_cache():
    """Each test starts with no compiled bundled template, so the cache of another test cannot hide a compile."""
    with messages._BUNDLED_LOCK:
        saved = dict(messages._BUNDLED_ENTRIES)
        messages._BUNDLED_ENTRIES.clear()
    yield
    with messages._BUNDLED_LOCK:
        messages._BUNDLED_ENTRIES.clear()
        messages._BUNDLED_ENTRIES.update(saved)


@pytest.fixture
def compiles(monkeypatch):
    """The names of the templates that ``_compile_skye`` is asked to build."""
    names: list[str] = []
    real = messages._compile_skye

    def counting(name, text, filename, *rest):
        names.append(name)
        return real(name, text, filename, *rest)

    monkeypatch.setattr(messages, "_compile_skye", counting)
    return names


# -- compile at the first use ---------------------------------------------------------------------------------------------


def test_the_construction_compiles_nothing(compiles):
    builder = BasePromptBuilder()
    assert compiles == []
    assert len(BUNDLED) >= 6
    assert builder.get_template("agent_react")  # the text is read at registration
    assert compiles == []


def test_the_first_use_of_a_template_compiles_it_once(compiles):
    builder = BasePromptBuilder()
    builder.get_template_variables("text_summarization")
    builder.get_template_variables("text_summarization")
    builder.describe("text_summarization")
    assert compiles == ["text_summarization"]


def test_a_second_builder_compiles_nothing_through_the_process_cache(compiles):
    BasePromptBuilder().get_template_variables("text_summarization")
    second = BasePromptBuilder()
    second.get_template_variables("text_summarization")
    assert compiles == ["text_summarization"]


def test_the_metadata_of_the_listing_needs_no_compile(compiles):
    builder = BasePromptBuilder()
    key = builder._latest_key("text_summarization")
    assert builder._template_metadata[key] == {"name": "text_summarization", "version": "1.0", "format": "skye"}
    assert "text_summarization" in builder._latest
    assert compiles == []


def test_a_template_of_the_user_under_a_bundled_name_replaces_the_pending_one(compiles):
    builder = BasePromptBuilder()
    builder.register_template("text_summarization", "Hello {{ name }}", version="1.0", from_string=True)
    assert builder.render("text_summarization", {"name": "Ada"})[-1].content == "Hello Ada"
    assert compiles == []


def test_a_partial_builder_compiles_for_itself_through_the_cache(compiles):
    builder = BasePromptBuilder()
    part = builder.partial(persona="a poet")
    part.get_template_variables("text_summarization")
    builder.get_template_variables("text_summarization")
    assert compiles == ["text_summarization"]


def test_two_threads_that_use_one_pending_template_compile_it_once(monkeypatch):
    calls: list[str] = []
    real = messages._compile_skye

    def slow(name, text, filename, *rest):
        calls.append(name)
        time.sleep(0.05)
        return real(name, text, filename, *rest)

    monkeypatch.setattr(messages, "_compile_skye", slow)
    builder = BasePromptBuilder()
    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def use() -> None:
        try:
            barrier.wait()
            builder.get_template_variables("text_summarization")
        except Exception as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=use) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert calls == ["text_summarization"]


# -- a mistake shows at the first use -------------------------------------------------------------------------------------


def test_a_broken_bundled_file_fails_at_its_first_use_with_its_name(tmp_path: Path, compiles):
    (tmp_path / "broken.skye").write_text(
        'prompt "broken" {\n  message "user" { text = \n', encoding="utf-8"
    )
    (tmp_path / "fine.skye").write_text(
        'prompt "fine" {\n  message "user" { text = "hi" }\n}\n', encoding="utf-8"
    )
    builder = BasePromptBuilder()
    assert (
        load_default_templates(builder, tmp_path) == 2
    )  # registered, nothing compiled, nothing raised
    assert compiles == []
    with pytest.raises(ValidationError, match="broken"):
        builder.get_template_variables("broken")
    with pytest.raises(
        ValidationError, match="broken"
    ):  # the error is not kept as a silent skip: the next use raises it again
        builder.render("broken", {})
    assert builder.render("fine", {})[-1].content == "hi"


def test_a_bundled_file_that_cannot_be_read_is_skipped_with_a_warning(tmp_path: Path, caplog):
    (
        tmp_path / "unreadable.skye"
    ).mkdir()  # a folder with the name of a template: reading it raises OSError
    builder = BasePromptBuilder()
    with caplog.at_level(logging.WARNING, logger="skye.prompts.loaders"):
        assert load_default_templates(builder, tmp_path) == 0
    assert any(getattr(record, "template", None) == "unreadable" for record in caplog.records)
    with pytest.raises(KeyError):
        builder.get_template("unreadable")


def test_a_template_of_the_user_with_a_bad_body_is_rejected_when_it_is_registered():
    builder = BasePromptBuilder()
    with pytest.raises(ValidationError):
        builder.register_template(
            "mine", 'prompt "mine" {\n  message "user" { text = \n', from_string=True
        )
    with pytest.raises(KeyError):
        builder.get_template("mine")


def test_a_template_of_the_user_is_validated_not_trusted(monkeypatch):
    seen: list[bool] = []
    real = messages._compile_skye

    def spy(name, text, filename, *rest):
        from skye.base import validated

        seen.append(validated._TRUSTED.get())
        return real(name, text, filename, *rest)

    monkeypatch.setattr(messages, "_compile_skye", spy)
    builder = BasePromptBuilder()
    builder.register_template(
        "mine", 'prompt "mine" {\n  message "user" { text = "hi" }\n}\n', from_string=True
    )
    builder.get_template_variables("text_summarization")
    assert seen == [
        False,
        True,
    ]  # the user's template was validated; the bundled one was built with trusted()


# -- the trusted build gives the same objects -----------------------------------------------------------------------------


def _sample(variable):
    """A value of the type that a variable declares (and of its fields), so that most templates render."""
    fields = {f.name: _sample(f) for f in (getattr(variable, "fields", None) or [])}
    if variable.type == "number":
        return 3
    if variable.type == "bool":
        return True
    if variable.type == "map":
        return fields
    if variable.type == "list":
        item = getattr(variable, "item_type", None)
        value = fields or {"number": 3, "bool": True, "map": {}}.get(item, "a")
        return [value, value]
    return "sample"


@pytest.mark.parametrize("path", BUNDLED, ids=lambda p: p.stem)
def test_the_trusted_build_of_a_bundled_template_equals_the_validated_build(path: Path):
    text = path.read_text(encoding="utf-8")
    read = {"filename": str(path), "resolver": file_resolver(path), "key": str(path.resolve())}
    with trusted():
        fast = build(text, **read)
    slow = build(text, **read)
    assert fast.diagnostics == slow.diagnostics == []
    assert fast.prompt(path.stem) == slow.prompt(path.stem)


def test_the_bundled_templates_render_the_same_with_and_without_the_validation():
    fast = BasePromptBuilder()  # compiles at the first use, with trusted()
    slow = BasePromptBuilder()
    for path in BUNDLED:
        key = slow._latest_key(path.stem)
        slow._pending.pop(key)
        slow._entries[key] = messages._compile_skye(
            path.stem,
            path.read_text(encoding="utf-8"),
            str(path),
            file_resolver(path),
            str(path.resolve()),
        )  # validated
    rendered = 0
    for path in BUNDLED:
        variables = {
            v.name: _sample(v) for v in slow._entry(slow._latest_key(path.stem)).spec.variables
        }
        outcome = []
        for builder in (fast, slow):
            try:
                outcome.append([(m.role, m.content) for m in builder.render(path.stem, variables)])
            except (
                Exception
            ) as error:  # the same mistake with and without the validation is the same result
                outcome.append((type(error).__name__, str(error)))
        assert outcome[0] == outcome[1], path.stem
        rendered += isinstance(outcome[0], list)
    assert (
        rendered >= 4
    )  # most templates render with the sample values, so the test sees real output
