"""The size report adds up and names every component (task 24.1 of the spec).

It tests the report and enforces no limit: the limit is `test_core_footprint`.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest

from tests.budget import size_report
from tests.budget.measure import ROOT
from tests.budget.size_report import KINDS, METADATA, TOP_LEVEL, format_text, main, measure

PACKAGE = ROOT / "src" / "skye"


def _bytes_of_tree() -> int:
    return sum(
        path.stat().st_size
        for path in PACKAGE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def _components_on_disk() -> set[str]:
    found = set()
    for entry in PACKAGE.iterdir():
        if entry.is_dir() and any(
            f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"
            for f in entry.rglob("*")
        ):
            found.add(entry.name)
    return found


@pytest.fixture(scope="module")
def tree():
    before = _bytes_of_tree()
    start = time.perf_counter()
    sizes = measure(PACKAGE)
    seconds = time.perf_counter() - start
    after = _bytes_of_tree()
    return sizes, before, after, seconds


def test_the_components_add_up_to_the_total(tree) -> None:
    sizes = tree[0]
    assert sum(sizes.by_component.values()) == sizes.total


def test_the_kinds_add_up_to_the_total(tree) -> None:
    sizes = tree[0]
    assert set(sizes.by_kind) == set(KINDS)
    assert sum(sizes.by_kind.values()) == sizes.total


def test_the_kinds_add_up_to_the_files_of_the_tree(tree) -> None:
    sizes, before, after, _seconds = tree
    kinds = sum(sizes.by_kind[kind] for kind in ("docstrings", "comments", "code", "data"))
    # Another process may write a file while the tree is read: the total sits between the two reads.
    assert min(before, after) <= kinds <= max(before, after)


def test_the_report_names_every_component_of_the_tree(tree) -> None:
    sizes = tree[0]
    text = format_text(sizes)
    for name in _components_on_disk():
        assert name in sizes.by_component, name
        assert name in text, name
    assert TOP_LEVEL in sizes.by_component  # skye/__init__.py and the other files of the top level


def test_every_kind_has_a_figure_and_the_python_is_split(tree) -> None:
    sizes = tree[0]
    assert all(sizes.by_kind[kind] > 0 for kind in KINDS)
    assert sizes.files > 0


def test_the_source_is_read_in_a_few_seconds(tree) -> None:
    assert tree[3] < 5


def test_the_command_prints_the_tables_and_the_budget_and_exits_zero(capsys) -> None:
    assert main(["--source"]) == 0
    out = capsys.readouterr().out
    assert "By component" in out and "By kind" in out and "Largest data folders" in out
    assert "[core] max_installed_mb = " in out
    assert "Total " in out


def test_the_command_writes_markdown_to_the_ci_summary(tmp_path, monkeypatch, capsys) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("SKYE_BUDGET_REPORT", str(summary))
    assert main(["--source"]) == 0
    capsys.readouterr()
    text = summary.read_text(encoding="utf-8")
    assert "| component | KB | share |" in text and "| kind | KB | share |" in text
    assert "max_installed_mb" in text


def test_split_python_adds_up_and_finds_docstrings_and_comments() -> None:
    source = (
        b'"""Module doc."""\n\n# a comment\n\n\ndef f():\n    """Doc."""\n    return 1  # tail\n'
    )
    code, docstrings, comments = size_report.split_python(source)
    assert code + docstrings + comments == len(source)
    assert docstrings == len(b"Module doc.") + len(b"Doc.")
    assert comments == len(b"# a comment") + len(b"# tail")


def test_split_python_counts_a_file_that_does_not_parse_as_code() -> None:
    assert size_report.split_python(b"def (:\n") == (7, 0, 0)


def test_a_wheel_is_measured_with_its_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "skyeai-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("skye/__init__.py", '"""Skye."""\n')
        archive.writestr("skye/base/a.py", "x = 1  # one\n")
        archive.writestr("skye/prompts/templates/p.skye", "prompt p {}\n")
        archive.writestr("skye/base/__pycache__/a.cpython-313.pyc", "ignored")
        archive.writestr("skyeai-0.0.0.dist-info/METADATA", "Name: skyeai\n")
    sizes = measure(wheel)
    assert sizes.files == 4
    assert set(sizes.by_component) == {TOP_LEVEL, "base", "prompts", METADATA}
    assert sum(sizes.by_component.values()) == sizes.total == sum(sizes.by_kind.values())
    assert sizes.by_kind["data"] == len("prompt p {}\n") + len("Name: skyeai\n")
    assert sizes.data_folders == {"prompts/templates": len("prompt p {}\n")}
