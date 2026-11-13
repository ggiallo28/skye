"""The Claude Code skill that ships with the package: it has the official layout, it installs, and
it cannot drift from the library.

Layout (the one the official skill-creator uses): a short ``SKILL.md`` that routes to
    ``references/*.md`` (one small file per
topic), and ``evals/`` with ``evals.json`` (test prompts and expectations) and
``trigger_evals.json`` (queries that should and
should not trigger the skill). The installer copies ``SKILL.md`` and ``references/``, not
``evals/``.

Whoever changes the command line, the ``.skye`` grammar, the public API or a rule must update the
matching file in the same
change (a rule of ``.kiro/steering/00-rules.md``); these tests fail when a file names something that
does not exist or shows a
``skye`` example that does not pass ``skye check``.
"""

from __future__ import annotations

import argparse
import json
import re
from importlib import resources
from pathlib import Path

import pytest

from skye.base.dsl import ALLOWED_FUNCTIONS, TEMPLATES, check_text
from skye.base.dsl.build import PREFIXES
from skye.base.dsl.specs import STRATEGIES
from skye.base.exceptions import ConfigurationError
from skye.utils.cli import _build_parser, main
from skye.utils.skill import (
    install_skill,
    reference_names,
    reference_text,
    skill_files,
    skill_path,
    skill_text,
    skills_dir,
)
from tests.unit.dsl.doc_examples import resolver, split

ROOT = Path(__file__).resolve().parents[3]
LINK = re.compile(r"\]\((references/[\w.-]+\.md)\)")
SKILL_DIR = resources.files("skye.utils").joinpath("claude_skill", "skye")

#: What the official ``quick_validate.py`` of the skill-creator accepts in the frontmatter.
ALLOWED_FRONTMATTER = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}


def _frontmatter() -> dict[str, str]:
    head = skill_text().split("---")[1]
    return dict(re.findall(r"^([\w-]+): (.*)$", head, re.MULTILINE))


def _everything() -> str:
    return "\n".join(skill_files().values())


# -- the layout ---------------------------------------------------------------------------------


def test_the_frontmatter_follows_the_official_rules() -> None:
    front = _frontmatter()
    assert set(front) <= ALLOWED_FRONTMATTER
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", front["name"]) and len(front["name"]) <= 64
    assert front["name"] == "skye"
    description = front["description"]
    assert 100 <= len(description) <= 1024
    assert "<" not in description and ">" not in description


def test_skill_md_is_minimal() -> None:
    lines = skill_text().strip().splitlines()
    assert len(lines) <= 45, f"SKILL.md has {len(lines)} lines; move detail to references/"


def test_every_reference_is_small_and_has_a_title() -> None:
    for name, text in skill_files().items():
        if name.startswith("references/"):
            assert len(text.strip().splitlines()) <= 120, f"{name} is too long; split it by topic"
            assert text.startswith("# "), f"{name} has no title"


def test_skill_md_links_every_reference_and_every_link_exists() -> None:
    linked = set(LINK.findall(skill_text()))
    existing = {name for name in skill_files() if name.startswith("references/")}
    assert (
        linked == existing
    ), f"linked only: {sorted(linked - existing)}; not linked: {sorted(existing - linked)}"


def test_the_references_link_only_to_references() -> None:
    for name, text in skill_files().items():
        if name.startswith("references/"):
            for target in re.findall(r"\]\(([\w.-]+\.md)\)", text):
                assert (
                    f"references/{target}" in skill_files()
                ), f"{name} links to a missing {target}"


def test_the_evals_are_in_the_official_format() -> None:
    data = json.loads(SKILL_DIR.joinpath("evals", "evals.json").read_text(encoding="utf-8"))
    assert data["skill_name"] == "skye"
    ids = [item["id"] for item in data["evals"]]
    assert (
        len(data["evals"]) >= 5
        and len(ids) == len(set(ids))
        and all(isinstance(i, int) for i in ids)
    )
    for item in data["evals"]:
        assert isinstance(item["prompt"], str) and len(item["prompt"]) > 40
        assert isinstance(item["expected_output"], str) and item["expected_output"]
        assert isinstance(item["files"], list)
        assert item["expectations"] and all(isinstance(e, str) and e for e in item["expectations"])


def test_the_trigger_queries_have_both_kinds() -> None:
    data = json.loads(SKILL_DIR.joinpath("evals", "trigger_evals.json").read_text(encoding="utf-8"))
    assert all(set(item) == {"query", "should_trigger"} for item in data)
    assert sum(1 for item in data if item["should_trigger"]) >= 8
    assert sum(1 for item in data if not item["should_trigger"]) >= 8


def test_the_evals_are_not_shipped_to_the_user() -> None:
    assert not any(name.startswith("evals/") for name in skill_files())


# -- no drift from the library ------------------------------------------------------------------


def _subcommands(parser: argparse.ArgumentParser) -> list[str]:
    names: list[str] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                names.append(name)
                names.extend(_subcommands(sub))
    return names


def test_the_cli_reference_names_every_command_and_flag() -> None:
    text = reference_text("cli")
    for name in set(_subcommands(_build_parser())):
        assert re.search(
            rf"\bskye (check|new|skill)?\b.*\b{name}\b|\bskye {name}\b", text
        ), f"cli.md does not show `{name}`"
    for flag in (
        "--schema",
        "--registry",
        "--template",
        "--force",
        "--scope",
        "--dir",
        "-o",
        "--list",
    ):
        assert flag in text, f"cli.md does not show {flag}"
    for kind, templates in TEMPLATES.items():
        for template in templates:
            assert f"`{template}`" in text, f"cli.md does not list the {kind} template {template}"


def test_the_references_cover_kinds_functions_strategies_and_prefixes() -> None:
    text = _everything()
    for kind in TEMPLATES:
        assert reference_text(
            kind
        ), kind  # one reference per block kind: router.md, flow.md, prompt.md
    for function in ALLOWED_FUNCTIONS:
        assert f"`{function}`" in reference_text(
            "language"
        ), f"language.md does not list the function {function}"
    for strategy in STRATEGIES:
        assert strategy in reference_text(
            "router"
        ), f"router.md does not list the strategy {strategy}"
    for prefix in PREFIXES:
        assert prefix in reference_text(
            "language"
        ), f"language.md does not explain the prefix {prefix}"
    assert "wait" in text and "on_event" in text  # what is not available is said, not hidden


def test_every_skye_example_in_the_skill_passes_the_checker() -> None:
    examples, sets = [], []
    for name, text in skill_files().items():
        plain, titled = split(text)
        examples += [(name, block) for block in plain]
        sets += [(name, title, titled) for title in titled]  # the titled fences of a file are one example
    assert len(examples) >= 4 and sets
    for name, example in examples:
        problems = check_text(example, name)
        assert not problems, (name, [p.message for p in problems])
    for name, title, files in sets:
        problems = check_text(files[title], f"{name}:{title}", resolver=resolver(files), key=title)
        assert not problems, (name, title, [p.message for p in problems])


def test_the_skill_does_not_promise_what_is_not_built() -> None:
    text = reference_text("python-api")
    assert "Not built yet" in text and "Flow.from_file" in text


# -- the installer ------------------------------------------------------------------------------


def test_install_writes_skill_md_and_the_references_but_not_the_evals(tmp_path: Path) -> None:
    target, status = install_skill(directory=tmp_path)
    assert status == "installed"
    assert target == tmp_path / "skye" / "SKILL.md"
    for name, text in skill_files().items():
        assert (tmp_path / "skye" / name).read_text(encoding="utf-8") == text
    assert not (tmp_path / "skye" / "evals").exists()
    assert install_skill(directory=tmp_path)[1] == "up to date"


def test_install_refuses_to_replace_a_different_file_without_force(tmp_path: Path) -> None:
    install_skill(directory=tmp_path)
    edited = tmp_path / "skye" / "references" / "flow.md"
    edited.write_text("my own version\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        install_skill(directory=tmp_path)
    assert "--force" in str(caught.value)
    assert edited.read_text(encoding="utf-8") == "my own version\n"
    assert install_skill(directory=tmp_path, force=True)[1] == "updated"
    assert edited.read_text(encoding="utf-8") == reference_text("flow")


def test_install_adds_a_missing_file_without_force(tmp_path: Path) -> None:
    install_skill(directory=tmp_path)
    (tmp_path / "skye" / "references" / "cli.md").unlink()
    assert install_skill(directory=tmp_path)[1] == "updated"
    assert (tmp_path / "skye" / "references" / "cli.md").read_text(
        encoding="utf-8"
    ) == reference_text("cli")


def test_scopes_point_to_the_claude_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert skills_dir("project") == tmp_path / ".claude" / "skills"
    assert skill_path("project") == tmp_path / ".claude" / "skills" / "skye" / "SKILL.md"
    assert skills_dir("user").parts[-2:] == (".claude", "skills")
    with pytest.raises(ConfigurationError):
        skills_dir("nowhere")


def test_the_command_installs_prints_and_shows_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["skill", "install", "--dir", str(tmp_path)]) == 0
    assert "installed" in capsys.readouterr().out
    assert main(["skill", "install", "--dir", str(tmp_path)]) == 0
    assert "up to date" in capsys.readouterr().out
    (tmp_path / "skye" / "SKILL.md").write_text("edited\n", encoding="utf-8")
    assert main(["skill", "install", "--dir", str(tmp_path)]) == 2
    assert "--force" in capsys.readouterr().err
    assert main(["skill", "install", "--dir", str(tmp_path), "--force"]) == 0
    assert "updated" in capsys.readouterr().out
    assert main(["skill", "print"]) == 0
    assert capsys.readouterr().out == skill_text()
    assert main(["skill", "print", "flow"]) == 0
    assert capsys.readouterr().out == reference_text("flow")
    assert main(["skill", "print", "nothing"]) == 2
    assert "References:" in capsys.readouterr().err
    monkeypatch.chdir(tmp_path)
    assert main(["skill", "path", "--scope", "project"]) == 0
    assert capsys.readouterr().out.strip() == str(
        tmp_path / ".claude" / "skills" / "skye" / "SKILL.md"
    )


def test_the_reference_names_are_the_ones_skill_md_links() -> None:
    assert reference_names() == sorted(Path(p).stem for p in LINK.findall(skill_text()))


# -- the skill must change when Skye changes: coverage read from the library itself
# ------------------
#
# These tests read the live command line, the block models, the language keywords and the public
# functions, and fail when the
# skill does not mention one. Adding a command, an option, a field, a keyword or a public function
# therefore forces the author to
# update the skill (or to say, in the exclusion lists below, why it is internal).


def _options(parser: argparse.ArgumentParser) -> set[str]:
    found: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found |= _options(sub)
        else:
            found |= {o for o in action.option_strings if o not in ("-h", "--help")}
    return found


def _field_names(*classes: type) -> set[str]:
    import dataclasses

    return {f.name for cls in classes for f in dataclasses.fields(cls)}


def _missing(names: set[str], text: str) -> list[str]:
    return sorted(
        name for name in names if not re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text)
    )


def test_every_command_line_option_is_in_the_cli_reference() -> None:
    missing = _missing(_options(_build_parser()), reference_text("cli"))
    assert (
        not missing
    ), f"references/cli.md does not mention {missing}: document the new option in the skill"


def test_every_router_field_is_in_the_router_reference() -> None:
    from skye.base.dsl import specs

    internal = {
        "name",
        "routes",
        "targets",
        "retry_policies",
        "allowed_fails_policies",
        "alias",
        "error_type",
        "fallback_targets",
    }
    fields = (
        _field_names(
            specs.RouterSpec,
            specs.RouteSpec,
            specs.TargetSpec,
            specs.RetryPolicySpec,
            specs.AllowedFailsPolicySpec,
        )
        - internal
    )
    missing = _missing(fields, reference_text("router"))
    assert (
        not missing
    ), f"references/router.md does not mention {missing}: document the new field in the skill"
    for block in ("route", "target", "retry_policy", "allowed_fails_policy", "fallback"):
        assert block in reference_text("router")


def test_every_flow_field_and_branch_is_in_the_flow_reference() -> None:
    from skye.base.dsl import specs

    internal = {
        "name",
        "nodes",
        "steps",
        "branches",
        "otherwise",
        "fields",
        "line",
        "column",
        "type",
        "default",
        "required",
        "value",
    }
    fields = (
        _field_names(
            specs.FlowSpec,
            specs.StepSpec,
            specs.ParallelSpec,
            specs.ChoiceSpec,
            specs.BranchSpec,
            specs.ContextSpec,
            specs.RetrySpec,
        )
        - internal
    )
    missing = _missing(
        fields | {"when", "else", "context", "parallel", "choice", "step", "end", "item"},
        reference_text("flow"),
    )
    assert not missing, (
        f"references/flow.md does not mention {missing}: document the new field or keyword in the "
        f"skill"
    )


def test_every_prompt_field_and_kind_is_in_the_prompt_reference() -> None:
    from skye.base.dsl import specs

    internal = {
        "name",
        "parts",
        "kind",
        "children",
        "items",
        "condition",
        "variable",
        "role_from",
        "type",
        "default",
        "required",
    }
    fields = _field_names(specs.PromptSpec, specs.PromptPartSpec, specs.VariableSpec) - internal
    keywords = {"message", "placeholder", "when", "each", "text", "variables", "allow_missing"}
    missing = _missing(fields | keywords, reference_text("prompt"))
    assert not missing, (
        f"references/prompt.md does not mention {missing}: document the new field or keyword in "
        f"the skill"
    )


def test_every_version_2_word_is_named_as_not_available() -> None:
    import importlib

    build = importlib.import_module("skye.base.dsl.build")
    words = set(build._V2_FLOW) | set(build._V2_PROMPT)
    missing = _missing(
        words, reference_text("language") + reference_text("flow") + reference_text("prompt")
    )
    assert not missing, (
        f"the skill does not say that {missing} are not available yet (or they became available: "
        f"update it)"
    )


def test_every_public_function_of_the_parser_package_is_in_the_python_reference() -> None:
    import skye.base.dsl as dsl

    # Names that are plumbing, not API a user or a model calls; add a name here only to say it is
    # internal.
    internal = {
        "tokenize",
        "did_you_mean",
        "suggest",
        "parse_collect",
        "check_expression",
        "evaluate",
        "parse_duration",
        "cache_info",
        "clear_cache",
    }
    functions = {
        n
        for n in dsl.__all__
        if callable(getattr(dsl, n)) and not isinstance(getattr(dsl, n), type)
    } - internal
    missing = _missing(functions, reference_text("python-api"))
    assert not missing, (
        f"references/python-api.md does not mention {missing}: document the new function in the "
        f"skill, or list it as internal here"
    )


def test_the_language_reference_lists_every_block_kind_and_the_duration_units() -> None:
    text = reference_text("language")
    for kind in ("router", "flow", "prompt"):
        assert kind in text
    for unit in ('"30s"', '"5m"', '"24h"'):
        assert unit in text


# -- the installed copy follows the package -------------------------------------------------------


def _pretend_the_package_changed(
    monkeypatch: pytest.MonkeyPatch, extra: str = "\nA new rule.\n"
) -> None:
    import skye.utils.skill as skill

    original = skill.skill_files

    def changed() -> dict[str, str]:
        files = dict(original())
        files["references/flow.md"] = files["references/flow.md"] + extra
        return files

    monkeypatch.setattr(skill, "skill_files", changed)
    monkeypatch.setattr(skill, "package_version", lambda: "9.9.9")


def test_status_says_not_installed_then_up_to_date(tmp_path: Path) -> None:
    from skye.utils.skill import skill_status

    assert skill_status(directory=tmp_path)[0] == "not installed"
    install_skill(directory=tmp_path)
    assert skill_status(directory=tmp_path)[0] == "up to date"


def test_a_skill_nobody_edited_is_updated_when_the_package_changes_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skye.utils.skill import skill_status

    install_skill(directory=tmp_path)
    _pretend_the_package_changed(monkeypatch)
    state, message = skill_status(directory=tmp_path)
    assert state == "outdated" and "9.9.9" in message and "skye skill install" in message
    assert install_skill(directory=tmp_path)[1] == "updated"
    assert "A new rule." in (tmp_path / "skye" / "references" / "flow.md").read_text(
        encoding="utf-8"
    )
    assert skill_status(directory=tmp_path)[0] == "up to date"


def test_a_file_edited_by_hand_is_kept_when_the_package_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skye.utils.skill import skill_status

    install_skill(directory=tmp_path)
    mine = tmp_path / "skye" / "references" / "flow.md"
    mine.write_text("my notes\n", encoding="utf-8")
    _pretend_the_package_changed(monkeypatch)
    state, message = skill_status(directory=tmp_path)
    assert state == "edited" and "references/flow.md" in message
    with pytest.raises(ConfigurationError):
        install_skill(directory=tmp_path)
    assert mine.read_text(encoding="utf-8") == "my notes\n"
    assert install_skill(directory=tmp_path, force=True)[1] == "updated"
    assert "A new rule." in mine.read_text(encoding="utf-8")


def test_a_file_the_package_no_longer_has_is_removed_if_it_was_not_edited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import skye.utils.skill as skill

    install_skill(directory=tmp_path)
    old = tmp_path / "skye" / "references" / "rules.md"
    original = skill.skill_files

    def without_rules() -> dict[str, str]:
        files = dict(original())
        del files["references/rules.md"]
        return files

    monkeypatch.setattr(skill, "skill_files", without_rules)
    assert install_skill(directory=tmp_path)[1] == "updated"
    assert not old.exists()


def test_a_skill_installed_before_the_record_existed_is_treated_as_edited_and_needs_force(
    tmp_path: Path,
) -> None:
    from skye.utils.skill import MANIFEST, skill_status

    install_skill(directory=tmp_path)
    (tmp_path / "skye" / MANIFEST).unlink()
    (tmp_path / "skye" / "SKILL.md").write_text("an older version\n", encoding="utf-8")
    assert skill_status(directory=tmp_path)[0] == "edited"
    with pytest.raises(ConfigurationError):
        install_skill(directory=tmp_path)


def test_the_status_command_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skill", "status", "--dir", str(tmp_path)]) == 1
    assert "not installed" in capsys.readouterr().out
    assert main(["skill", "install", "--dir", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["skill", "status", "--dir", str(tmp_path)]) == 0
    assert "up to date" in capsys.readouterr().out


# -- the rule and the packaging -----------------------------------------------------------------


def test_the_rule_to_update_the_skill_is_written_in_the_steering_rules() -> None:
    rules = (ROOT / ".kiro" / "steering" / "00-rules.md").read_text(encoding="utf-8")
    assert "src/skye/utils/claude_skill/skye/" in rules
    assert "references" in rules and "SKILL.md" in rules


def test_the_skill_is_part_of_the_wheel() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/skye"]' in pyproject  # the whole package folder, data files included
    assert not re.search(r"exclude\s*=.*(SKILL|references|claude_skill)", pyproject)
