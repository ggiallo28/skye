"""Discovery of installed plugins with a fake ``entry_points`` whose values are modules
(plugins:4.1, 4.5; 4.7 extends this file).

An entry point is a module: loading it imports the module, and the decorators of ``skye.Plugins`` in
it register. The fake modules here are real
files on ``sys.path`` that are removed from ``sys.modules`` after each test.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import skye.base.plugins as base_plugins
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar
from skye.utils import plugins as discovery
from skye.utils.plugins import PluginReport, discover, plugin_reports

PRELUDE = "from skye.base.plugins import Plugins\nplugins = Plugins()\n"
ACME = (
    PRELUDE
    + "plugins.backend('acme-store', dict)\nplugins.provider('acme', object, function='model')\n"
)
TINY = PRELUDE + "plugins.tokenizer('tiny-tok', len)\n"
B_AGENT = PRELUDE + "plugins.agent('b-agent', dict)\n"
B_STORE = PRELUDE + "plugins.backend('b-store', dict)\n"


class FakeEntryPoint:
    """The part of ``importlib.metadata.EntryPoint`` that discovery reads: loading imports a module,
    as the real one does."""

    def __init__(
        self,
        name: str,
        module: str | None = None,
        *,
        dist: Any = "missing",
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._module = module
        self._error = error
        self.loads = 0
        self.dist = (
            SimpleNamespace(metadata={"Name": f"dist-{name}"}, version="1.2.3")
            if dist == "missing"
            else dist
        )

    def load(self) -> Any:
        self.loads += 1
        if self._error is not None:
            raise self._error
        return importlib.import_module(self._module or self.name)


@pytest.fixture
def make_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Write a module on ``sys.path`` and forget it from ``sys.modules`` when the test ends."""
    monkeypatch.syspath_prepend(str(tmp_path))
    names: list[str] = []

    def make(name: str, body: str) -> str:
        (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
        names.append(name)
        importlib.invalidate_caches()
        return name

    request.addfinalizer(lambda: [sys.modules.pop(name, None) for name in names])
    return make


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    monkeypatch.setattr(discovery, "_entry_points", lambda: list(entry_points))


@pytest.fixture(autouse=True)
def clean_reports(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discovery, "_reports", ())


# -- discover: an entry point is a module
# -------------------------------------------------------------------------


def test_discover_imports_each_entry_point_module_and_reports_what_it_registered(
    monkeypatch, make_module
):
    first = FakeEntryPoint("acme", make_module("acme_plugin", ACME))
    second = FakeEntryPoint("tiny", make_module("tiny_plugin", TINY))
    install(monkeypatch, second, first)
    registrar = Registrar()
    reports = discover(registrar)
    assert [r.name for r in reports] == ["acme", "tiny"]  # sorted by entry-point name
    assert reports[0] == PluginReport(
        "acme",
        "dist-acme",
        "1.2.3",
        True,
        None,
        {"provider": ["acme"], "backend": ["acme-store"]},
    )
    assert reports[1].registered == {"tokenizer": ["tiny-tok"]}
    assert registrar.get("backend", "acme-store") is dict
    assert first.loads == second.loads == 1


def test_a_provider_that_is_not_a_model_shows_its_function_in_the_report(monkeypatch, make_module):
    two = PRELUDE + (
        "plugins.provider('acme', object, function='model')\n"
        "plugins.provider('acme', object, function='embedding')\n"
        "plugins.provider('acme-decide', object, function='decision')\n"
    )
    install(monkeypatch, FakeEntryPoint("acme", make_module("acme_two_plugin", two)))
    (report,) = discover(Registrar())
    assert report.registered == {"provider": ["acme", "acme (embedding)", "acme-decide (decision)"]}


def test_a_second_function_under_a_name_that_exists_is_reported(monkeypatch, make_module):
    base = PRELUDE + "plugins.provider('acme', object, function='model')\n"
    more = PRELUDE + "plugins.provider('acme', object, function='embedding')\n"
    install(monkeypatch, FakeEntryPoint("more", make_module("acme_more_plugin", more)))
    registrar = Registrar()
    registrar.provider("acme", object, function="model")
    (report,) = discover(registrar)
    assert report.registered == {
        "provider": ["acme (embedding)"]
    }  # the name was there, the function is new
    assert base  # the module a plugin would have written for the first function


def test_the_decorators_of_the_module_register_on_the_registrar_given_not_on_the_default(
    monkeypatch, make_module
):
    body = PRELUDE + "@plugins.agent('reverse')\nclass Reverse:\n    pass\n"
    install(monkeypatch, FakeEntryPoint("rev", make_module("rev_plugin", body)))
    registrar = Registrar()
    default_before = base_plugins._default
    (report,) = discover(registrar)
    assert report.loaded and report.registered == {"agent": ["reverse"]}
    assert registrar.has("agent", "reverse")
    assert base_plugins._default is default_before  # the default is put back
    assert not get_registrar().has("agent", "reverse")


def test_the_default_is_put_back_when_the_import_fails(monkeypatch, make_module):
    install(
        monkeypatch,
        FakeEntryPoint("bad", make_module("bad_plugin", "raise RuntimeError('boom')\n")),
    )
    default_before = base_plugins._default
    (report,) = discover(Registrar())
    assert not report.loaded
    assert base_plugins._default is default_before


def test_with_the_default_registrar_nothing_is_swapped(monkeypatch, make_module):
    default = get_registrar()
    install(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar()
    monkeypatch.setattr(base_plugins, "_default", registrar)
    try:
        (report,) = discover(registrar)
        assert report.loaded and base_plugins._default is registrar
        assert registrar.has("backend", "acme-store")
    finally:
        monkeypatch.setattr(base_plugins, "_default", default)


def test_a_failure_to_load_is_logged_once_reported_and_skipped(monkeypatch, make_module, caplog):
    install(
        monkeypatch,
        FakeEntryPoint("bad", error=ImportError("no module x")),
        FakeEntryPoint("good", make_module("acme_plugin", ACME)),
    )
    registrar = Registrar()
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        reports = discover(registrar)
    bad, good = reports
    assert (bad.name, bad.loaded, bad.registered) == ("bad", False, {})
    assert "ImportError" in bad.error and "no module x" in bad.error
    assert good.loaded and registrar.names("provider", "model") == ["acme"]  # the scan went on
    records = [r for r in caplog.records if r.name == "skye.utils.plugins"]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert (records[0].entry_point, records[0].distribution) == ("bad", "dist-bad")
    assert "no module x" in records[0].error


def test_a_module_that_cannot_be_imported_is_reported(monkeypatch, make_module, caplog):
    body = "import a_module_that_does_not_exist_anywhere\n"
    install(monkeypatch, FakeEntryPoint("lost", make_module("lost_plugin", body)))
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        (report,) = discover(Registrar())
    assert not report.loaded and "ModuleNotFoundError" in report.error
    assert len([r for r in caplog.records if r.name == "skye.utils.plugins"]) == 1


def test_a_module_that_fails_while_it_registers_keeps_what_it_registered_and_is_reported(
    monkeypatch, make_module, caplog
):
    body = PRELUDE + "plugins.backend('half', dict)\nraise RuntimeError('boom')\n"
    install(
        monkeypatch,
        FakeEntryPoint("broken", make_module("broken_plugin", body)),
        FakeEntryPoint("good", make_module("acme_plugin", ACME)),
    )
    registrar = Registrar()
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        reports = discover(registrar)
    assert [r.loaded for r in reports] == [False, True]
    assert "boom" in reports[0].error
    assert reports[0].registered == {"backend": ["half"]}  # what it did before it failed
    assert registrar.has("backend", "half")
    assert len([r for r in caplog.records if r.name == "skye.utils.plugins"]) == 1


def test_a_name_already_registered_makes_the_module_fail_and_the_scan_goes_on(
    monkeypatch, make_module
):
    install(
        monkeypatch,
        FakeEntryPoint("acme", make_module("acme_plugin", ACME)),
        FakeEntryPoint("tiny", make_module("tiny_plugin", TINY)),
    )
    registrar = Registrar()
    registrar.backend("acme-store", dict)
    acme, tiny = discover(registrar)
    assert not acme.loaded and "acme-store" in acme.error and "ConfigurationError" in acme.error
    assert tiny.loaded and registrar.has("tokenizer", "tiny-tok")


def test_a_module_the_program_imported_before_the_scan_registers_once(monkeypatch, make_module):
    """Importing the module is the registration: the scan finds it imported, adds nothing and finds
    no duplicate."""
    name = make_module("acme_plugin", ACME)
    registrar = Registrar()
    default = base_plugins._default
    monkeypatch.setattr(base_plugins, "_default", registrar)  # the program registers on the default
    try:
        importlib.import_module(name)
    finally:
        monkeypatch.setattr(base_plugins, "_default", default)
    assert registrar.names("backend") == ["acme-store"]
    entry_point = FakeEntryPoint("acme", name)
    install(monkeypatch, entry_point)
    (report,) = discover(registrar)
    assert report.loaded and report.error is None
    assert report.registered == {}  # nothing new: it was registered when the program imported it
    assert registrar.names("backend") == ["acme-store"] and registrar.names(
        "provider", "model"
    ) == ["acme"]
    assert entry_point.loads == 1


def test_a_second_scan_does_not_register_twice(monkeypatch, make_module):
    install(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar()
    first = discover(registrar)
    second = discover(registrar)
    assert first[0].registered and second[0].loaded and second[0].registered == {}
    assert registrar.names("backend") == ["acme-store"]


def test_an_entry_point_without_a_distribution_has_none(monkeypatch, make_module):
    install(monkeypatch, FakeEntryPoint("loose", make_module("loose_plugin", ACME), dist=None))
    (report,) = discover(Registrar())
    assert (report.distribution, report.version, report.loaded) == (None, None, True)


def test_no_entry_point_is_an_empty_report(monkeypatch):
    install(monkeypatch)
    assert discover(Registrar()) == []
    assert plugin_reports() == ()


def test_the_reports_of_the_last_scan_are_kept(monkeypatch, make_module):
    assert plugin_reports() == ()
    install(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    reports = discover(Registrar())
    assert plugin_reports() == tuple(reports)
    install(monkeypatch)
    discover(Registrar())
    assert plugin_reports() == ()


def test_the_real_metadata_scan_finds_nothing_for_an_unused_group_and_does_not_raise():
    assert isinstance(discover(Registrar()), list)


# -- failures: logged once, skipped, and the error after the scan (plugins:4.4; Requirements 57.6,
# 57.7) ----------


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name == "skye.utils.plugins" and r.levelno == logging.WARNING
    ]


def test_the_warning_is_emitted_once_even_when_two_lookups_trigger_the_scan(
    monkeypatch, make_module, caplog
):
    CountingScan(monkeypatch, FakeEntryPoint("bad", error=ImportError("no module x")))
    registrar = Registrar(scan=True)
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        for kind, name in (("backend", "first-miss"), ("provider", "second-miss")):
            with pytest.raises(ConfigurationError):
                registrar.get(kind, name)
    (record,) = _warnings(caplog)
    assert record.entry_point == "bad" and "no module x" in record.error


def test_two_failing_entry_points_are_each_logged_once_and_the_good_one_loads(
    monkeypatch, make_module, caplog
):
    install(
        monkeypatch,
        FakeEntryPoint("a-bad", error=ImportError("first")),
        FakeEntryPoint("b-good", make_module("acme_plugin", ACME)),
        FakeEntryPoint("c-bad", make_module("bad_plugin", "raise RuntimeError('second')\n")),
    )
    registrar = Registrar()
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        reports = discover(registrar)
    assert [r.loaded for r in reports] == [False, True, False]  # a failure never stops the next
    assert [r.entry_point for r in _warnings(caplog)] == ["a-bad", "c-bad"]
    assert registrar.names("provider", "model") == ["acme"]


def test_the_extra_of_a_module_that_raises_carries_the_three_keys(monkeypatch, make_module, caplog):
    body = "raise ValueError('bad setting')\n"
    install(
        monkeypatch,
        FakeEntryPoint("loose", make_module("loose_plugin", body), dist=None),
        FakeEntryPoint("owned", make_module("owned_plugin", body)),
    )
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        reports = discover(Registrar())
    loose, owned = _warnings(caplog)
    assert (loose.entry_point, loose.distribution) == ("loose", None)  # no distribution is None
    assert (owned.entry_point, owned.distribution) == ("owned", "dist-owned")
    assert owned.error == reports[1].error == "ValueError: bad setting"
    assert owned.getMessage() == "plugin entry point skipped"


def test_an_unknown_name_after_the_scan_lists_the_names_of_the_kind_in_its_text(
    monkeypatch, make_module
):
    CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("provider", "other", "model")
    assert "no provider named 'other' for the function 'model'" in str(caught.value)
    assert "registered: acme" in str(caught.value)  # the name the scan brought is listed
    assert caught.value.details["known"] == ["acme"]


def test_an_unknown_name_after_the_scan_lists_the_failures_of_the_scan(
    monkeypatch, make_module, caplog
):
    CountingScan(
        monkeypatch,
        FakeEntryPoint("bad", make_module("bad_plugin", "raise RuntimeError('plugin boom')\n")),
    )
    registrar = Registrar(scan=True)
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        with pytest.raises(ConfigurationError) as caught:
            registrar.get("backend", "nope")
    assert "plugin boom" in str(caught.value)
    assert "bad" in str(caught.value)


# -- the scan at the first miss of the registrar (plugins:4.2)
# --------------------------------------------------


class CountingScan:
    """Replaces the metadata read and counts the scans."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
        self.scans = 0
        self.entry_points = list(entry_points)
        monkeypatch.setattr(discovery, "_entry_points", self)

    def __call__(self) -> list[FakeEntryPoint]:
        self.scans += 1
        return list(self.entry_points)


def test_a_miss_scans_once_and_finds_the_name_the_plugin_registered(monkeypatch, make_module):
    scan = CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    assert scan.scans == 0  # building the registrar scans nothing
    assert registrar.get("provider", "acme", "model") is not None
    assert scan.scans == 1


def test_a_hit_does_not_scan(monkeypatch, make_module):
    scan = CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    registrar.backend("mine", dict)
    assert registrar.get("backend", "mine") is dict
    assert registrar.names("backend") == ["mine"] and registrar.has("backend", "mine")
    assert scan.scans == 0


def test_the_group_is_read_once_whatever_the_number_of_misses(monkeypatch):
    scan = CountingScan(monkeypatch)
    registrar = Registrar(scan=True)
    for _ in range(3):
        with pytest.raises(ConfigurationError):
            registrar.get("backend", "nope")
    with pytest.raises(ConfigurationError):
        registrar.get("provider", "also-nope", "model")
    assert scan.scans == 1


def test_the_miss_is_looked_up_again_once_after_the_scan(monkeypatch, make_module):
    """The name that the scan brings is returned by the same ``get`` that missed."""
    CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    assert registrar.get("provider", "acme", "model")
    assert registrar.names("provider", "model") == ["acme"]


def test_a_name_the_scan_does_not_bring_is_still_an_error_that_lists_the_known_names(
    monkeypatch, make_module
):
    CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    with pytest.raises(ConfigurationError) as caught:
        registrar.get("provider", "other", "model")
    assert caught.value.details["known"] == ["acme"]


def test_a_private_registrar_never_scans(monkeypatch, make_module):
    scan = CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar()
    with pytest.raises(ConfigurationError):
        registrar.get("provider", "acme", "model")
    assert scan.scans == 0


def test_listing_and_testing_a_name_do_not_scan(monkeypatch, make_module):
    scan = CountingScan(monkeypatch, FakeEntryPoint("acme", make_module("acme_plugin", ACME)))
    registrar = Registrar(scan=True)
    assert registrar.names("provider", "model") == [] and not registrar.has(
        "provider", "acme", "model"
    )
    assert scan.scans == 0


def test_a_lookup_made_while_scanning_does_not_start_another_scan(monkeypatch, make_module):
    registrar = Registrar(scan=True)
    body = (
        "from skye.base.exceptions import ConfigurationError\n"
        "from skye.base.plugins import get_registrar\n"
        "try:\n"
        "    get_registrar().get('backend', 'missing')  # a miss inside the scan\n"
        "except ConfigurationError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('the miss must raise')\n"
    )
    scan = CountingScan(monkeypatch, FakeEntryPoint("greedy", make_module("greedy_plugin", body)))
    with pytest.raises(ConfigurationError):
        registrar.get("backend", "x")
    assert scan.scans == 1


def test_import_skye_loads_no_entry_point(tmp_path):
    """A fake distribution whose entry point raises on load: ``import skye`` and a first lookup that
    hits must not touch it."""
    import subprocess
    import sys

    dist = tmp_path / "boom_plugin-0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: boom-plugin\nVersion: 0.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text("[skye.plugins]\nboom = boom_plugin\n", encoding="utf-8")
    (tmp_path / "boom_plugin.py").write_text(
        "raise RuntimeError('loaded at import')\n", encoding="utf-8"
    )
    code = (
        "import sys, skye\n"
        "from skye.base.plugins import Registrar\n"
        "r = Registrar(scan=True); r.backend('x', dict); r.get('backend', 'x')\n"
        "assert 'boom_plugin' not in sys.modules, 'entry point loaded'\n"
        "assert 'skye.utils.plugins' not in sys.modules, 'scan module imported'\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(tmp_path)
            + ":"
            + str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stdout + done.stderr


# -- the `plugins` allowlist of the configuration file (plugins:4.3, Requirement 57.5)
# ---------------------------


def _write_config(tmp_path, monkeypatch, body: str) -> None:
    path = tmp_path / "skye.json"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("SKYE_CONFIG", str(path))


def test_without_the_key_every_entry_point_loads(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"log_level": "INFO"}')
    a, b = (
        FakeEntryPoint("a", make_module("a_plugin", ACME)),
        FakeEntryPoint("b", make_module("b_plugin", B_AGENT)),
    )
    install(monkeypatch, a, b)
    reports = discover(Registrar())
    assert [r.loaded for r in reports] == [True, True] and a.loads == b.loads == 1
    assert not any(r.skipped for r in reports)


def test_without_a_file_every_entry_point_loads(monkeypatch, make_module):
    monkeypatch.delenv("SKYE_CONFIG", raising=False)
    install(monkeypatch, FakeEntryPoint("a", make_module("a_plugin", ACME)))
    assert [r.loaded for r in discover(Registrar())] == [True]


def test_only_the_listed_entry_points_load(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"plugins": ["a"]}')
    a, b = (
        FakeEntryPoint("a", make_module("a_plugin", ACME)),
        FakeEntryPoint("b", make_module("b_plugin", B_AGENT)),
    )
    install(monkeypatch, a, b)
    registrar = Registrar()
    reports = {r.name: r for r in discover(registrar)}
    assert reports["a"].loaded and not reports["a"].skipped
    assert reports["b"].skipped and not reports["b"].loaded and reports["b"].error is None
    assert (a.loads, b.loads) == (1, 0)
    assert registrar.names("agent") == []  # what b would have registered is not there


def test_an_unlisted_entry_point_that_raises_on_load_is_never_loaded(
    monkeypatch, tmp_path, caplog, make_module
):
    _write_config(tmp_path, monkeypatch, '{"plugins": ["good"]}')
    boom = FakeEntryPoint("boom", error=RuntimeError("must not be loaded"))
    install(monkeypatch, FakeEntryPoint("good", make_module("good_plugin", ACME)), boom)
    with caplog.at_level(logging.WARNING, logger="skye.utils.plugins"):
        reports = discover(Registrar())
    assert boom.loads == 0 and [r.name for r in reports if r.skipped] == ["boom"]
    assert not [
        r for r in caplog.records if r.name == "skye.utils.plugins"
    ]  # skipping by the allowlist is not a failure


def test_an_empty_list_loads_none(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"plugins": []}')
    a = FakeEntryPoint("a", make_module("a_plugin", ACME))
    install(monkeypatch, a)
    assert [r.skipped for r in discover(Registrar())] == [True] and a.loads == 0


def test_a_listed_name_that_is_not_installed_is_not_an_error(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"plugins": ["a", "not-installed"]}')
    install(monkeypatch, FakeEntryPoint("a", make_module("a_plugin", ACME)))
    reports = discover(Registrar())
    assert [r.name for r in reports] == ["a"] and reports[0].loaded


def test_an_explicit_allowlist_wins_over_the_file(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"plugins": ["a"]}')
    a, b = (
        FakeEntryPoint("a", make_module("a_plugin", ACME)),
        FakeEntryPoint("b", make_module("b_plugin", PRELUDE)),
    )
    install(monkeypatch, a, b)
    reports = {r.name: r for r in discover(Registrar(), allowlist=["b"])}
    assert reports["b"].loaded and reports["a"].skipped and a.loads == 0


@pytest.mark.parametrize(
    "body",
    ['{"plugins": "acme"}', '{"plugins": [1]}', '{"plugins": [""]}', '{"plugins": {"a": 1}}'],
)
def test_a_plugins_key_that_is_not_a_list_of_names_is_a_configuration_error_naming_the_key(
    monkeypatch, tmp_path, body, make_module
):
    _write_config(tmp_path, monkeypatch, body)
    install(monkeypatch, FakeEntryPoint("a", make_module("a_plugin", ACME)))
    with pytest.raises(ConfigurationError) as caught:
        discover(Registrar())
    assert "plugins" in str(caught.value.details) or "plugins" in caught.value.message


def test_the_scan_does_not_change_a_logger_level(monkeypatch, tmp_path, make_module):
    """Reading the allowlist must not apply the ``log_level`` of the file: the scan runs at a
    lookup, not at start-up."""
    _write_config(tmp_path, monkeypatch, '{"log_level": "ERROR", "plugins": ["a"]}')
    install(monkeypatch, FakeEntryPoint("a", make_module("a_plugin", ACME)))
    logger = logging.getLogger("skye")
    before = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        discover(Registrar())
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(before)


def test_the_allowlist_works_through_the_registrar_miss(monkeypatch, tmp_path, make_module):
    _write_config(tmp_path, monkeypatch, '{"plugins": ["a"]}')
    install(
        monkeypatch,
        FakeEntryPoint("a", make_module("a_plugin", ACME)),
        FakeEntryPoint("b", make_module("b_plugin", B_STORE)),
    )
    registrar = Registrar(scan=True)
    assert registrar.get("backend", "acme-store") is dict
    with pytest.raises(ConfigurationError):
        registrar.get("backend", "b-store")  # b was left out by the allowlist


def test_an_unlisted_entry_point_is_not_imported_by_the_real_scan(tmp_path):
    """A fake distribution whose entry point raises when imported: the allowlist keeps it from ever
    loading."""
    import subprocess
    import sys

    dist = tmp_path / "boom_plugin-0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: boom-plugin\nVersion: 0.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        "[skye.plugins]\nboom = boom_plugin:plugin\n", encoding="utf-8"
    )
    (tmp_path / "boom_plugin.py").write_text("raise RuntimeError('loaded')\n", encoding="utf-8")
    config = tmp_path / "skye.json"
    config.write_text('{"plugins": ["something-else"]}', encoding="utf-8")
    code = (
        "import sys\n"
        "from skye.base.plugins import Registrar\n"
        "from skye.utils.plugins import discover\n"
        "reports = discover(Registrar())\n"
        "assert [(r.name, r.skipped) for r in reports] == [('boom', True)], reports\n"
        "assert 'boom_plugin' not in sys.modules\n"
        "print('ok')\n"
    )
    import os
    import pathlib

    env = {
        **os.environ,
        "SKYE_CONFIG": str(config),
        "PYTHONPATH": str(tmp_path)
        + ":"
        + str(pathlib.Path(__file__).resolve().parents[3] / "src"),
    }
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stdout + done.stderr
