"""Report what the installed package weighs, by component and by kind (task 24.1 of the spec).

It reports and never enforces: the test that enforces the limit is `test_core_footprint`. Run it
at the end of a wave:

    make size                                       # the source tree, a second
    make size-wheel                                 # builds the wheel and measures that
    uv run python -m tests.budget.size_report --wheel path/to/skyeai.whl

A figure is the uncompressed size in bytes of a file, as the install writes it (pycache is not
counted). A Python file is split with the standard library: the docstrings (`ast`), the comments
(`tokenize`) and the rest, which is the code. Every other file is data.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import sys
import tempfile
import tokenize
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from tests.budget.measure import ROOT, build_wheel, cleanup, load_budgets, report

KINDS = ("code", "docstrings", "comments", "data")
TOP_LEVEL = "(top level files)"
METADATA = "(metadata)"
DATA_FOLDERS_SHOWN = 6


@dataclass
class Sizes:
    """The figures of one measurement, in bytes."""

    origin: str
    files: int = 0
    total: int = 0
    by_component: dict[str, int] = field(default_factory=dict)
    by_kind: dict[str, int] = field(default_factory=lambda: {kind: 0 for kind in KINDS})
    data_folders: dict[str, int] = field(default_factory=dict)

    def add(self, component: str, kind: str, size: int) -> None:
        self.total += size
        self.by_component[component] = self.by_component.get(component, 0) + size
        self.by_kind[kind] += size


def split_python(source: bytes) -> tuple[int, int, int]:
    """The bytes of ``source`` that are code, docstrings and comments; the three add up to it."""
    total = len(source)
    docstrings = comments = 0
    try:
        text = source.decode("utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node, clean=False)
                if docstring:
                    docstrings += len(docstring.encode("utf-8"))
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments += len(token.string.encode("utf-8"))
    except (SyntaxError, UnicodeDecodeError, tokenize.TokenError, ValueError):
        return total, 0, 0
    docstrings = min(docstrings, total)
    comments = min(comments, total - docstrings)
    return total - docstrings - comments, docstrings, comments


def _entries(target: Path):
    """``(parts, bytes)`` for each file of a package tree or of a wheel, the parts from ``skye``."""
    if target.is_dir():
        for path in sorted(target.rglob("*")):
            parts = path.relative_to(target).parts
            if not path.is_file() or "__pycache__" in parts or path.suffix == ".pyc":
                continue
            try:
                yield ("skye", *parts), path.read_bytes()
            except OSError:
                continue
        return
    with zipfile.ZipFile(target) as wheel:
        for info in wheel.infolist():
            if not info.is_dir() and "__pycache__" not in info.filename:
                yield tuple(info.filename.split("/")), wheel.read(info)


def measure(target: Path) -> Sizes:
    """Measure a package tree (the folder ``src/skye``) or a wheel (a ``.whl`` file)."""
    sizes = Sizes(origin=str(target))
    for parts, content in _entries(target):
        sizes.files += 1
        if parts[0] != "skye":
            sizes.add(METADATA, "data", len(content))
            continue
        below = parts[1:]
        component = below[0] if len(below) > 1 else TOP_LEVEL
        if parts[-1].endswith(".py"):
            code, docstrings, comments = split_python(content)
            sizes.add(component, "code", code)
            sizes.add(component, "docstrings", docstrings)
            sizes.add(component, "comments", comments)
        else:
            sizes.add(component, "data", len(content))
            folder = "/".join(below[:-1][:2]) or "."
            sizes.data_folders[folder] = sizes.data_folders.get(folder, 0) + len(content)
    return sizes


def _kb(size: int) -> str:
    return f"{size / 1000:9.1f}"


def _share(size: int, total: int) -> str:
    return f"{(size / total * 100) if total else 0:5.1f}%"


def _budget_line(sizes: Sizes) -> str:
    limit = load_budgets()["core"]["max_installed_mb"]
    now = sizes.total / 1e6
    return f"[core] max_installed_mb = {limit}, now {now:.2f}, free {limit - now:.2f} MB"


def format_text(sizes: Sizes) -> str:
    """The report as plain text."""
    total = sizes.total
    lines = [
        f"Size of skye: {sizes.origin} ({sizes.files} files)",
        "",
        f"{'By component':24s}{'KB':>10s}{'share':>8s}",
    ]
    for name, size in sorted(sizes.by_component.items(), key=lambda item: -item[1]):
        lines.append(f"{name:24s}{_kb(size)}{_share(size, total):>8s}")
    lines += ["", f"{'By kind':24s}{'KB':>10s}{'share':>8s}"]
    for kind in KINDS:
        lines.append(
            f"{kind:24s}{_kb(sizes.by_kind[kind])}{_share(sizes.by_kind[kind], total):>8s}"
        )
    lines += ["", f"{'Largest data folders':24s}{'KB':>10s}{'share':>8s}"]
    largest = sorted(sizes.data_folders.items(), key=lambda item: -item[1])[:DATA_FOLDERS_SHOWN]
    for name, size in largest:
        lines.append(f"{name:24s}{_kb(size)}{_share(size, total):>8s}")
    lines += ["", f"Total {total / 1e6:.2f} MB ({total} bytes)", _budget_line(sizes)]
    return "\n".join(lines)


def format_markdown(sizes: Sizes) -> list[str]:
    """The same figures as markdown lines, for the summary of a CI job."""
    total = sizes.total
    lines = ["| component | KB | share |", "|---|---|---|"]
    for name, size in sorted(sizes.by_component.items(), key=lambda item: -item[1]):
        lines.append(f"| {name} | {size / 1000:.1f} | {_share(size, total).strip()} |")
    lines += ["", "| kind | KB | share |", "|---|---|---|"]
    for kind in KINDS:
        size = sizes.by_kind[kind]
        lines.append(f"| {kind} | {size / 1000:.1f} | {_share(size, total).strip()} |")
    lines += ["", f"Total {total / 1e6:.2f} MB. `{_budget_line(sizes)}`"]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="size_report", description="Report the size of the skye package."
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--source",
        action="store_true",
        help="read src/skye directly (fast); the default builds the wheel",
    )
    which.add_argument("--wheel", metavar="FILE", help="measure this wheel instead of building one")
    args = parser.parse_args(argv)
    if args.source:
        sizes = measure(ROOT / "src" / "skye")
    elif args.wheel:
        sizes = measure(Path(args.wheel))
    else:
        workdir = Path(tempfile.mkdtemp(prefix="skye-size-"))
        try:
            sizes = measure(build_wheel(workdir))
        finally:
            cleanup(workdir)
    print(format_text(sizes))
    if os.environ.get("SKYE_BUDGET_REPORT"):
        for line in format_markdown(sizes):
            report(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
