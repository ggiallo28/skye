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
NAMES = ("text_classification", "text_explanation", "text_summarization")


def _pack(templates: dict[str, bytes]) -> bytes:
    spec = importlib.util.spec_from_file_location("hatch_build", ROOT / "scripts" / "hatch_build.py")
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
    members = {f"{n}.skye": (SOURCE / f"{n}.skye").read_bytes() for n in NAMES}
    members.update({f"common/{p.name}": p.read_bytes() for p in (SOURCE / "common").glob("*.skye")})
    archive.write_bytes(_pack(members))
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", empty)
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", archive)
    monkeypatch.setattr(loaders, "_archive_index", None)
    return archive


def test_export_from_a_source_checkout_writes_every_template(tmp_path, capsys) -> None:
    folder = tmp_path / "out"
    assert main(["prompt", "export", str(folder)]) == 0
    assert "wrote 11 prompts" in capsys.readouterr().out
    written = sorted(p.stem for p in folder.glob("*.skye"))
    assert len(written) == 11
    assert (folder / "common" / "system_prompt.skye").read_bytes() == (SOURCE / "common" / "system_prompt.skye").read_bytes()
    assert (folder / "text_summarization.skye").read_bytes() == (SOURCE / "text_summarization.skye").read_bytes()


def test_export_from_the_archive_writes_the_templates_of_the_archive(
    as_wheel, tmp_path, capsys
) -> None:
    folder = tmp_path / "deep" / "out"  # the folder, and its parents, are created
    assert main(["prompt", "export", str(folder)]) == 0
    assert "wrote 3 prompts" in capsys.readouterr().out
    assert sorted(p.stem for p in folder.glob("*.skye")) == sorted(NAMES)
    assert (folder / "text_summarization.skye").read_text(encoding="utf-8") == (SOURCE / "text_summarization.skye").read_text(
        encoding="utf-8"
    )


def test_export_does_not_replace_a_file_without_force(as_wheel, tmp_path, capsys) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "text_summarization.skye").write_text("mine", encoding="utf-8")
    assert main(["prompt", "export", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "text_summarization.skye" in err and "--force" in err
    assert (folder / "text_summarization.skye").read_text(encoding="utf-8") == "mine"
    assert not (folder / "text_classification.skye").exists()  # nothing is written when one would be replaced
    assert main(["prompt", "export", str(folder), "--force"]) == 0
    assert (folder / "text_summarization.skye").read_text(encoding="utf-8") != "mine"


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
    assert main(["prompt", "info", "text_summarization"]) == 0
    assert "Inputs" in capsys.readouterr().out
    assert main(["prompt", "info", "text_summarization", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "text_summarization"


def test_info_of_an_unknown_name_lists_the_bundled_ones_of_the_archive(as_wheel, capsys) -> None:
    assert main(["prompt", "info", "no-such"]) == 2
    err = capsys.readouterr().err
    assert "no-such" in err and "text_summarization" in err and "text_summarization" in err


def test_the_diagnostics_name_the_archive_entry(as_wheel, tmp_path, monkeypatch, capsys) -> None:
    """A bundled prompt that does not build is reported with where it is: `templates.zip/<name>.skye`."""
    broken = tmp_path / "broken.zip"
    broken.write_bytes(_pack({"broken.skye": b'prompt "broken" { message "system" {'}))
    monkeypatch.setattr(loaders, "TEMPLATES_ARCHIVE", broken)
    monkeypatch.setattr(loaders, "_archive_index", None)
    assert main(["prompt", "info", "broken"]) == 1
    assert "broken.zip/broken.skye" in capsys.readouterr().out
