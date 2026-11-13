"""An environment variable in an include target is never expanded (Requirement 63.9).

The target is a plain relative path: ``$HOME`` and ``${HOME}`` are read as the letters they are, so
the resolver is asked for the literal name and a missing file is reported like any other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skye.base.dsl import build
from skye.utils.skye_files import file_resolver
from tests.unit.dsl.include_files import resolver

TARGETS = ["$HOME/x.skye", "${HOME}/x.skye"]


@pytest.mark.parametrize("target", TARGETS)
def test_the_resolver_is_asked_for_the_literal_name(target: str) -> None:
    calls: list[tuple[str, str | None]] = []
    document = build(
        f'include "{target}" as x\n', filename="app.skye", resolver=resolver({}, calls)
    )
    assert [name for name, _ in calls] == [target]
    (problem,) = document.diagnostics
    assert f'cannot read "{target}"' in problem.reason


@pytest.mark.parametrize("target", TARGETS)
def test_a_variable_that_names_a_real_file_is_still_not_expanded(
    target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "x.skye").write_text("---\npartial = true\n---\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    entry = tmp_path / "app.skye"
    resolve = file_resolver(entry)
    with pytest.raises(FileNotFoundError, match=str(tmp_path.resolve())):
        resolve(target, str(entry.resolve()))
