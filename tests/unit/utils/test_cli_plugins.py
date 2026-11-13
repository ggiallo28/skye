"""``skye plugins``: what is registered, and each entry point of the group ``skye.plugins`` (plugins:4.6, Requirement 57.9).

The command reads the default registrar and asks it to scan. Here the default registrar is a private one for the length of each test, with the
metadata replaced by fake entry points that are real modules on ``sys.path``, so the process-wide registrar and the reports of the last scan are
back as they were when the test ends.
"""

from __future__ import annotations

import json

import pytest

import skye.base.plugins as base_plugins
from skye.base.plugins import KINDS, Registrar
from skye.utils import plugins as discovery
from skye.utils.cli import main
from tests.unit.plugins.test_discovery import (  # noqa: F401  (make_module is a fixture)
    ACME,
    TINY,
    CountingScan,
    FakeEntryPoint,
    make_module,
)

BOOM = "raise RuntimeError('plugin boom')\n"


@pytest.fixture
def private_default(monkeypatch: pytest.MonkeyPatch) -> Registrar:
    """A private registrar that scans, made the default; the reports of the last scan are put back at the end."""
    registrar = Registrar(scan=True, builtin_plugins=base_plugins.BUILTIN_PLUGINS)
    monkeypatch.setattr(base_plugins, "_default", registrar)
    monkeypatch.setattr(discovery, "_reports", ())
    monkeypatch.setattr(discovery, "configured_plugins", lambda: None)
    return registrar


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["plugins", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_text_lists_the_built_ins_by_kind_and_says_none_when_nothing_is_installed(
    private_default, monkeypatch, capsys
):
    CountingScan(monkeypatch)
    code, out, err = run(capsys)
    assert code == 0 and err == ""
    assert "Built-in" in out
    for kind in KINDS:
        assert kind in out
    assert "memory" in out and "react" in out and "skyemcp" in out
    assert "entry-point group skye.plugins" in out and "none" in out


def test_json_has_the_keys_and_parses(private_default, monkeypatch, capsys):
    CountingScan(monkeypatch)
    code, out, _ = run(capsys, "--format", "json")
    data = json.loads(out)
    assert code == 0
    assert set(data) == {"builtin", "entry_points"}
    assert set(data["builtin"]) == set(KINDS)
    assert "memory" in data["builtin"]["backend"] and "react" in data["builtin"]["agent"]
    assert all(names == sorted(names) for names in data["builtin"].values())
    assert data["entry_points"] == []


def test_an_entry_point_that_loads_is_listed_with_what_it_registered(
    private_default, monkeypatch, make_module, capsys
):
    CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    code, out, _ = run(capsys)
    assert code == 0
    assert "acme  (dist-acme 1.2.3)  loaded" in out
    assert "backend: acme-store" in out and "provider: acme" in out
    # what the plugin registered is not in the built-in list
    assert "acme-store" not in out.split("Installed plugins")[0]


def test_json_reports_a_loaded_a_failed_and_a_skipped_entry_point(
    private_default, monkeypatch, make_module, capsys
):
    CountingScan(
        monkeypatch,
        FakeEntryPoint("acme", make_module("acme_plugin", ACME)),
        FakeEntryPoint("bad", make_module("bad_plugin", BOOM)),
        FakeEntryPoint("tiny", make_module("tiny_plugin", TINY)),
    )
    monkeypatch.setattr(discovery, "configured_plugins", lambda: ["acme", "bad"])
    code, out, _ = run(capsys, "--format", "json")
    assert code == 0  # a failed entry point is shown, it is not an error of the command
    by_name = {item["name"]: item for item in json.loads(out)["entry_points"]}
    assert set(by_name) == {"acme", "bad", "tiny"}
    for item in by_name.values():
        assert set(item) == {
            "name",
            "distribution",
            "version",
            "loaded",
            "skipped",
            "error",
            "registered",
        }
    assert by_name["acme"]["loaded"] is True and by_name["acme"]["error"] is None
    assert by_name["acme"]["registered"] == {"backend": ["acme-store"], "provider": ["acme"]}
    assert by_name["acme"]["distribution"] == "dist-acme" and by_name["acme"]["version"] == "1.2.3"
    assert by_name["bad"]["loaded"] is False and "plugin boom" in by_name["bad"]["error"]
    assert by_name["tiny"]["skipped"] is True and by_name["tiny"]["loaded"] is False
    assert by_name["tiny"]["error"] is None


def test_text_shows_a_failure_and_a_skip_and_still_exits_0(
    private_default, monkeypatch, make_module, capsys
):
    CountingScan(
        monkeypatch,
        FakeEntryPoint("bad", make_module("bad_plugin", BOOM)),
        FakeEntryPoint("tiny", make_module("tiny_plugin", TINY)),
    )
    monkeypatch.setattr(discovery, "configured_plugins", lambda: ["bad"])
    code, out, err = run(capsys)
    assert code == 0 and err == ""
    assert "bad  (dist-bad 1.2.3)  failed" in out
    assert "RuntimeError: plugin boom" in out
    assert "tiny  (dist-tiny 1.2.3)  skipped" in out
    assert "not in the plugins allowlist" in out


def test_an_unreadable_configuration_is_an_error_of_the_command(
    private_default, monkeypatch, capsys
):
    from skye.base.exceptions import ConfigurationError

    CountingScan(monkeypatch)

    def broken() -> None:
        raise ConfigurationError("the plugins key must be a list of names")

    monkeypatch.setattr(discovery, "configured_plugins", broken)
    code, out, err = run(capsys)
    assert code == 2 and out == ""
    assert "skye plugins: the plugins key must be a list of names" in err


def test_the_command_scans_once_and_leaves_the_default_registrar_alone(
    private_default, monkeypatch, make_module, capsys
):
    scan = CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    run(capsys)
    run(capsys, "--format", "json")
    assert scan.scans == 1
    assert base_plugins._default is private_default  # the test's own, put back by monkeypatch


def test_a_wrong_option_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        main(["plugins", "--format", "yaml"])
    assert caught.value.code == 2
