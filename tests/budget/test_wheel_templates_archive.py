"""The wheel carries the bundled templates as one `templates.zip` (task 24.7).

The build hook packs the stripped `.skye` templates into `skye/prompts/templates.zip` and keeps the loose files out of the wheel. The
archive is the same bytes for the same source, builds to the same objects as the stripped folder, and an installed wheel lists, shows and
exports the prompts from it and builds a `BasePromptBuilder` under `[prompts] max_builder_ms`.
"""

from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path

import pytest

from skye.dsl import build
from tests.budget import measure

ROOT = measure.ROOT
ARCHIVE = "skye/prompts/templates.zip"
SOURCE = ROOT / "src" / "skye" / "prompts" / "templates"

FRESH_BUILD = """
import time
import skye.prompts
from skye.prompts import BasePromptBuilder
start = time.perf_counter()
BasePromptBuilder()
print((time.perf_counter() - start) * 1000)
"""


@pytest.fixture(scope="module")
def wheels(tmp_path_factory) -> tuple[Path, Path]:
    first = measure.build_wheel(tmp_path_factory.mktemp("first"))
    second = measure.build_wheel(tmp_path_factory.mktemp("second"))
    return first, second


def _archive_bytes(wheel: Path) -> bytes:
    with zipfile.ZipFile(wheel) as z:
        return z.read(ARCHIVE)


def test_the_wheel_has_the_archive_and_no_loose_template(wheels) -> None:
    with zipfile.ZipFile(wheels[0]) as z:
        names = z.namelist()
    assert ARCHIVE in names
    assert [
        n for n in names if n.startswith("skye/prompts/templates/") and n.endswith(".skye")
    ] == []


def test_the_archive_has_the_forty_templates_sorted(wheels) -> None:
    with zipfile.ZipFile(io.BytesIO(_archive_bytes(wheels[0]))) as z:
        names = z.namelist()
    assert len(names) == 40
    assert names == sorted(names)
    assert names == sorted(p.name for p in SOURCE.glob("*.skye"))


def test_two_builds_give_the_same_archive_bytes(wheels) -> None:
    assert _archive_bytes(wheels[0]) == _archive_bytes(wheels[1])


def test_the_archive_templates_build_to_the_objects_of_the_folder(wheels) -> None:
    with zipfile.ZipFile(io.BytesIO(_archive_bytes(wheels[0]))) as z:
        different = [
            n
            for n in z.namelist()
            if build(z.read(n).decode("utf-8")) != build((SOURCE / n).read_text(encoding="utf-8"))
        ]
    assert not different, different


def _run(python: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(python), "-m", "skye.utils.cli", *args], capture_output=True, text=True, cwd=cwd
    )


def test_an_installed_wheel_lists_shows_and_exports_the_prompts(wheels, tmp_path, capsys) -> None:
    python = measure.make_env(wheels[0], None, tmp_path)
    listed = _run(python, "prompt", "list", cwd=tmp_path)
    assert listed.returncode == 0, listed.stderr
    assert "chat" in listed.stdout
    info = _run(python, "prompt", "info", "chat", cwd=tmp_path)
    assert info.returncode == 0, info.stderr
    out = tmp_path / "exported"
    done = _run(python, "prompt", "export", str(out), cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert len(list(out.glob("*.skye"))) == 40
    again = _run(python, "prompt", "export", str(out), cwd=tmp_path)
    assert again.returncode == 2
    assert _run(python, "prompt", "export", str(out), "--force", cwd=tmp_path).returncode == 0
    with capsys.disabled():
        print(f"\n{listed.stdout.splitlines()[:3]}\n{done.stdout.strip()}")


def test_a_builder_from_the_wheel_stays_below_the_limit(wheels, tmp_path) -> None:
    python = measure.make_env(wheels[0], None, tmp_path)
    budget = measure.load_budgets()["prompts"]
    times = [
        float(subprocess.check_output([str(python), "-c", FRESH_BUILD], text=True, cwd=tmp_path))
        for _ in range(budget["runs"])
    ]
    best = min(times)
    measure.report(
        f"| BasePromptBuilder() from the wheel archive | best of {budget['runs']}: {best:.1f} ms | max {budget['max_builder_ms']} ms | |"
    )
    assert best <= budget["max_builder_ms"], best
