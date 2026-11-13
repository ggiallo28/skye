"""Every ``skye`` code block in ``docs/`` and ``README.md``, and every ``.skye`` file in
``examples/``, passes ``skye check`` (Property 17).

A block that is meant to show an error is written with the ``text`` fence, not ``skye``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skye.base.dsl import check_text
from skye.utils.cli import main
from skye.utils.skye_files import file_resolver
from tests.unit.dsl.doc_examples import FENCE, resolver, split

ROOT = Path(__file__).resolve().parents[3]


def blocks() -> list[tuple[str, int, str]]:
    found = []
    pages = [*sorted((ROOT / "docs").rglob("*.md")), ROOT / "README.md"]
    for page in pages:
        if "_notes" in page.parts or not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        for match in FENCE.finditer(text):
            if match.group(1):
                continue  # one file of a multi-file example, checked with its set below
            if match.group(2).lstrip().startswith("--8<--"):
                continue  # a snippet of a file in examples/, checked as a file below
            line = text.count("\n", 0, match.start()) + 1
            found.append((str(page.relative_to(ROOT)), line, match.group(2)))
    return found


def example_sets() -> list[tuple[str, str, dict[str, str]]]:
    """Per page and per titled file: (page, title, all the titled files of the page)."""
    found = []
    for page in [*sorted((ROOT / "docs").rglob("*.md")), ROOT / "README.md"]:
        if "_notes" in page.parts or not page.exists():
            continue
        files = split(page.read_text(encoding="utf-8"))[1]
        found += [(str(page.relative_to(ROOT)), title, files) for title in files]
    return found


def test_the_language_page_has_examples() -> None:
    pages = {page for page, _, _ in blocks()}
    assert "docs/reference/skye-language.md" in pages
    assert sum(1 for page, _, _ in blocks() if page == "docs/reference/skye-language.md") >= 3


@pytest.mark.parametrize("page,line,text", blocks(), ids=lambda v: str(v)[:40])
def test_skye_block_passes_check(page: str, line: int, text: str) -> None:
    assert [d.format() for d in check_text(text, f"{page}:{line}")] == []


@pytest.mark.parametrize("page,title,files", example_sets(), ids=lambda v: str(v)[:40])
def test_every_file_of_a_multi_file_example_passes_check(
    page: str, title: str, files: dict[str, str]
) -> None:
    """A partial is checked for syntax; a prompt is checked with its includes read from the other fences of the page."""
    problems = check_text(files[title], f"{page}:{title}", resolver=resolver(files), key=title)
    assert [d.format() for d in problems] == []


def test_the_language_page_has_a_multi_file_example() -> None:
    titles = {title for page, title, _ in example_sets() if page == "docs/reference/skye-language.md"}
    assert {"lib/agent.skye", "lib/memory.skye", "tool_agent.skye", "chat_agent.skye"} <= titles


EXAMPLE_FILES = sorted((ROOT / "examples").rglob("*.skye"))


def test_the_examples_folder_has_skye_files() -> None:
    assert len(EXAMPLE_FILES) >= 2


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_skye_example_file_passes_check(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    diagnostics = check_text(
        text, str(path.relative_to(ROOT)), resolver=file_resolver(path), key=str(path.resolve())
    )
    assert [d.format() for d in diagnostics] == []


def test_the_cli_agrees_on_a_docs_block(tmp_path: Path) -> None:
    page, _, text = blocks()[0]
    file = tmp_path / "doc.skye"
    file.write_text(text, encoding="utf-8")
    assert main(["check", str(file)]) == 0
