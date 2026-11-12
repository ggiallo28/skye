"""``skye prompt export`` and ``skye prompt list/info`` with the folder of a source checkout and with the archive of a wheel (task 24.7)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from skye.prompts import loaders
from skye.utils.cli import main
from tests.budget import measure

ROOT = measure.ROOT
SOURCE = ROOT / "src" / "skye" / "prompts" / "templates"
NAMES = ("chat", "classification", "summarization")


def _pack(templates: dict[str, bytes]) -> bytes:
    spec = importlib.util.spec_from_file_location("hatch_build", ROOT / "hatch_build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.pack_templates(templates)


@pytest.fixture
def as_wheel(tmp_path, monkeypatch) -> Path:
    """The bundled templates as an installed wheel has them: an archive and an empty folder."""
    empty = tmp_path / "templates"
    empty.mkdir()
    archive = tmp_path / "templates.zip"
    archive.write_bytes(_pack({f"{n}.skye": (SOURCE / f"{n}.skye").read_bytes() for n in NAMES}))
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", empty)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", archive)
    monkeypatch.setattr(loaders, "_archive_index", None)
    return archive


def test_export_from_a_source_checkout_writes_every_template(tmp_path, capsys) -> None:
    folder = tmp_path / "out"
    assert main(["prompt", "export", str(folder)]) == 0
    assert "wrote 40 prompts" in capsys.readouterr().out
    written = sorted(p.stem for p in folder.glob("*.skye"))
    assert len(written) == 40
    assert (folder / "chat.skye").read_bytes() == (SOURCE / "chat.skye").read_bytes()


def test_export_from_the_archive_writes_the_templates_of_the_archive(
    as_wheel, tmp_path, capsys
) -> None:
    folder = tmp_path / "deep" / "out"  # the folder, and its parents, are created
    assert main(["prompt", "export", str(folder)]) == 0
    assert "wrote 3 prompts" in capsys.readouterr().out
    assert sorted(p.stem for p in folder.glob("*.skye")) == sorted(NAMES)
    assert (folder / "chat.skye").read_text(encoding="utf-8") == (SOURCE / "chat.skye").read_text(
        encoding="utf-8"
    )


def test_export_does_not_replace_a_file_without_force(as_wheel, tmp_path, capsys) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "chat.skye").write_text("mine", encoding="utf-8")
    assert main(["prompt", "export", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "chat.skye" in err and "--force" in err
    assert (folder / "chat.skye").read_text(encoding="utf-8") == "mine"
    assert not (
        folder / "summarization.skye"
    ).exists()  # nothing is written when one would be replaced
    assert main(["prompt", "export", str(folder), "--force"]) == 0
    assert (folder / "chat.skye").read_text(encoding="utf-8") != "mine"


def test_export_to_a_path_that_is_a_file_is_a_usage_error(as_wheel, tmp_path, capsys) -> None:
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")
    assert main(["prompt", "export", str(target)]) == 2
    assert "skye prompt export" in capsys.readouterr().err


def test_list_and_info_read_the_archive(as_wheel, capsys) -> None:
    assert main(["prompt", "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in rows] == sorted(NAMES)
    assert all(r["version"] for r in rows)
    assert main(["prompt", "info", "chat"]) == 0
    assert "Inputs" in capsys.readouterr().out
    assert main(["prompt", "info", "chat", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "chat"


def test_info_of_an_unknown_name_lists_the_bundled_ones_of_the_archive(as_wheel, capsys) -> None:
    assert main(["prompt", "info", "no-such"]) == 2
    err = capsys.readouterr().err
    assert "no-such" in err and "chat" in err and "summarization" in err


def test_the_diagnostics_name_the_archive_entry(as_wheel, tmp_path, monkeypatch, capsys) -> None:
    """A bundled prompt that does not build is reported with where it is: `templates.zip/<name>.skye`."""
    broken = tmp_path / "broken.zip"
    broken.write_bytes(_pack({"broken.skye": b'prompt "broken" { message "system" {'}))
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", broken)
    monkeypatch.setattr(loaders, "_archive_index", None)
    assert main(["prompt", "info", "broken"]) == 1
    assert "broken.zip/broken.skye" in capsys.readouterr().out
