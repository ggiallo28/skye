"""Registry, variables, validation, caching and loaders of the prompt builder (tasks 2.1 to 2.7)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import skye.prompts.messages as messages_module
from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.interfaces.prompt import PromptBuilderInterface
from skye.prompts import BasePromptBuilder
from skye.prompts.loaders import discover_templates, load_default_templates


@pytest.fixture(scope="module")
def shared() -> BasePromptBuilder:
    return BasePromptBuilder()


def fresh(shared: BasePromptBuilder) -> BasePromptBuilder:
    """A builder with the bundled templates, without reading the folder again."""
    return shared.partial()


# -- 2.1 variables from the engine's parser -------------------------------------------------------


def test_block_variables_include_conditions_and_filter_operands(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    builder.register_template(
        "t", "{{ name }}{{ '!' if mood else '' }}{{ things | map('y') | join }}"
    )
    assert builder.get_template_variables("t") == ["name", "mood", "things"]


def test_simple_variables_take_the_root_name(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{user.name} {items[0]} {user} {n:>{width}}")
    assert builder.get_template_variables("t") == ["user", "items", "n", "width"]


def test_metadata_lists_exactly_the_variables_found(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{{ a }}{{ b | default('') }}{{ c | default('') }}{{ text }}")
    meta = builder.get_template_metadata("t")
    assert meta["variables"] == ["a"]
    assert sorted(meta["variables"] + meta["optional_variables"]) == ["a", "b", "c", "text"]


# -- 2.2 validation with the parser ---------------------------------------------------------------


def test_registration_rejects_bad_syntax_with_the_engine_details(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    with pytest.raises(ValidationError, match=r"'broken'.*Unexpected token") as info:
        builder.register_template("broken", "{{ x y }}")
    assert info.value.details["template"] == "broken"
    with pytest.raises(KeyError):
        builder.get_template("broken")


def test_validate_template_never_raises(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    assert builder.validate_template("missing")["valid"] is False
    builder.register_template("t", "{{ a }}")
    builder._templates["t:1.0"] = "{{ x | }}"
    result = builder.validate_template("t")
    assert result["valid"] is False and result["errors"]
    builder.register_template("ok", "{{ a }} {{ text }}")
    result = builder.validate_template("ok")
    assert result == {
        "valid": True,
        "errors": [],
        "warnings": ["Variable 'a' has no default value"],
        "variables_found": ["a", "text"],
    }


# -- 2.3 missing required variables ---------------------------------------------------------------


def test_block_template_names_every_missing_variable_sorted(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{{ zeta }} {{ alpha }} {{ gamma | default('') }}")
    with pytest.raises(ValueError, match=r"^Missing required variables: alpha, zeta") as info:
        builder.render("t", {})
    assert isinstance(info.value, ValidationError)
    assert builder.render("t", {"zeta": "z", "alpha": "a"})[0].content == "z a "


def test_single_missing_variable_message(shared: BasePromptBuilder) -> None:
    builder = fresh(shared)
    builder.register_template("t", "Hi {{ who }}")
    with pytest.raises(ValueError, match="Missing required variable: who"):
        builder.render("t", {})


def test_defaults_partials_and_allowed_missing_satisfy_requirements(
    shared: BasePromptBuilder,
) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{{ a }}-{{ b }}-{{ c }}-{{ d | default('x') }}")
    builder.set_default_values({"a": "A"})
    builder.set_allowed_missing_variables(["c"])
    assert builder.partial(b="B").render("t", {})[0].content == "A-B--x"


# -- 2.4 ${VAR} substitution and logging ----------------------------------------------------------


def test_defaults_substitute_environment_variables(
    shared: BasePromptBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKYE_TEST_PERSONA", "a pirate")
    builder = fresh(shared)
    builder.register_template("t", "You are {{ persona }}.")
    builder.set_default_values({"persona": "${SKYE_TEST_PERSONA}"})
    assert builder.render("t", {})[0].content == "You are a pirate."


def test_missing_environment_variable_is_a_configuration_error(shared: BasePromptBuilder) -> None:
    with pytest.raises(ConfigurationError):
        fresh(shared).set_default_values({"x": "${SKYE_TEST_SURELY_UNSET_VARIABLE}"})


def test_loader_logs_instead_of_printing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "good.jinja").write_text("Hi {{ name }}")
    (tmp_path / "bad.jinja").write_text("{{ x y }}")
    builder = BasePromptBuilder()
    with caplog.at_level(logging.WARNING, logger="skye.prompts.loaders"):
        assert load_default_templates(builder, tmp_path) == 1
    assert capsys.readouterr().out == ""
    assert any(r.getMessage() == "Could not load template" for r in caplog.records)
    assert builder.get_template("good") == "Hi {{ name }}"


# -- 2.5 compile once, caches ---------------------------------------------------------------------


def test_rendering_reuses_the_compiled_template(
    shared: BasePromptBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = fresh(shared)
    builder.register_template("t", "Hi {{ name }}")

    def boom(source: str) -> None:
        raise AssertionError("compiled again")

    monkeypatch.setattr(messages_module, "compile_template", boom)
    assert builder.render("t", {"name": "Ada"})[0].content == "Hi Ada"
    assert builder.get_template_variables("t") == ["name"]


def test_fixed_examples_are_formatted_once_and_cache_is_bounded(shared: BasePromptBuilder) -> None:
    builder = BasePromptBuilder(max_cached_examples=2)
    calls: list[str] = []
    builder.register_filter("seen", lambda v: calls.append(v) or v)
    for name in ("a", "b", "c"):
        builder.register_template(name, "{{ examples }}")
        builder.add_examples(name, [{"q": name}], "Q: {{ q | seen }}")
    builder.render("a", {})
    builder.render("a", {})
    assert calls == ["a"]
    builder.render("b", {})
    builder.render("c", {})
    assert list(builder._example_cache) == ["b", "c"]
    builder.add_examples("b", [{"q": "new"}], "Q: {{ q }}")
    assert "Q: new" in builder.render("b", {})[0].content


def test_partial_shares_compiled_entries(shared: BasePromptBuilder) -> None:
    shared.get_template_variables("text_summarization")  # a bundled template is compiled at its first use (task 24.8)
    other = shared.partial(x="1")
    key = next(iter(shared._entries))
    assert other._entries[key] is shared._entries[key]
    assert other._templates[key] is shared._templates[key]


# -- 2.6 no macros --------------------------------------------------------------------------------


def test_register_jinja_macro_is_gone(shared: BasePromptBuilder) -> None:
    assert not hasattr(PromptBuilderInterface, "register_jinja_macro")
    assert not hasattr(shared, "register_jinja_macro")
    assert "Jinja2" not in (PromptBuilderInterface.register_filter.__doc__ or "")


def test_register_filter_replaces_register_jinja_filter_with_no_alias(
    shared: BasePromptBuilder,
) -> None:
    # Task 9.2, decision D77.
    assert "register_filter" in PromptBuilderInterface.__abstractmethods__
    assert not hasattr(PromptBuilderInterface, "register_jinja_filter")
    assert not hasattr(shared, "register_jinja_filter")
    builder = fresh(shared)
    builder.register_filter("shout", lambda v: f"{str(v).upper()}!")
    builder.register_template("t", "{{ name | shout }}")
    assert builder.render("t", {"name": "ada"})[0].content == "ADA!"


# -- 2.7 properties 1, 2, 10 (parametrized: Hypothesis is not a dev dependency) -------------------

TEXTS = ["", "plain", "Hi {name}", "{{ a }}{{ b | default('x') }}", "ünïcode {{ e }}", "a\n\nb"]
VERSIONS = ["1.0", "1.1", "2.0", "10.0-beta"]


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("version", VERSIONS)
def test_property_1_registry_round_trip(shared: BasePromptBuilder, text: str, version: str) -> None:
    builder = fresh(shared)
    builder.register_template("round", text, version)
    assert builder.get_template("round", version) == text
    assert builder.get_template("round") == text


@pytest.mark.parametrize(
    ("default", "partial", "provided", "expected"),
    [
        ("d", None, None, "d"),
        ("d", "p", None, "p"),
        ("d", "p", "v", "v"),
        ("d", None, "v", "v"),
        (None, "p", "v", "v"),
        (None, "p", None, "p"),
    ],
)
def test_property_2_merge_precedence(
    shared: BasePromptBuilder,
    default: str | None,
    partial: str | None,
    provided: str | None,
    expected: str,
) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{{ x }}")
    calls: list[int] = []
    if default is not None:
        builder.set_default_values({"x": lambda: calls.append(1) or default})
    if partial is not None:
        builder = builder.partial(x=partial)
    variables = {"x": provided} if provided is not None else {}
    assert builder.render("t", variables)[0].content == expected
    assert builder.render("t", variables)[0].content == expected
    assert len(calls) == (2 if expected == default else 0)


@pytest.mark.parametrize("bound", [{"a": "1"}, {"a": "1", "b": "2"}, {"text": "t"}])
def test_property_10_partial_leaves_the_original_unchanged(
    shared: BasePromptBuilder, bound: dict[str, str]
) -> None:
    builder = fresh(shared)
    builder.register_template("t", "{{ a }}")
    before = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in vars(builder).items()}
    child = builder.partial(**bound)
    child.register_template("only_child", "x")
    child.set_default_values({"z": "1"})
    child.add_examples("t", [{"input": "i", "output": "o"}])
    assert vars(builder) == before
    with pytest.raises(KeyError):
        builder.get_template("only_child")
    with pytest.raises(ValueError, match="Missing required variable: a"):
        builder.render("t", {})


def test_discover_prefers_skye(tmp_path: Path) -> None:
    for name in ("a.jinja", "a.skye", "b.txt", "c.tmpl"):
        (tmp_path / name).write_text("x")
    found = discover_templates(tmp_path)
    assert {k: v.name for k, v in found.items()} == {"a": "a.skye", "b": "b.txt", "c": "c.tmpl"}
