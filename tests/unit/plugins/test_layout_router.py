"""The layout of ``router/plugins`` (D110, Requirements 56.9, 56.10 and 58.1): one folder per
routing strategy, one door, the same file names."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.base.interfaces.router import RoutingStrategy
from skye.base.plugins import Registrar
from skye.router import plugins
from skye.router.routing_strategies import RouterStrategy

ROOT = Path(plugins.__file__).parent
FOLDERS = list(plugins.IMPLEMENTATIONS)
ALLOWED_FILES = {"__init__.py", "strategy.py"}
NAMES = [member.value for member in RoutingStrategy]
EXTRA = ["lazy_complex"]  # a built-in that is not a member of the enumeration (D113)
ALL_NAMES = NAMES + EXTRA


def test_the_folders_on_disk_are_the_implementations():
    on_disk = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert on_disk == sorted(FOLDERS)


def test_the_folders_are_the_members_of_the_enumeration_and_the_extra_built_ins():
    assert sorted(FOLDERS) == sorted(ALL_NAMES)


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_and_only_the_uniform_file_names(folder):
    files = {p.name for p in (ROOT / folder).iterdir() if p.is_file()}
    assert "__init__.py" in files
    assert files <= ALLOWED_FILES, sorted(files - ALLOWED_FILES)


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_resolves(folder):
    package = importlib.import_module(f"skye.router.plugins.{folder}")
    for name in package._LAZY:
        assert getattr(package, name) is not None, name
    with pytest.raises(AttributeError):
        package.not_a_name  # noqa: B018


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_inner_file_a_door_names_exists(folder):
    package = importlib.import_module(f"skye.router.plugins.{folder}")
    inner = {p.stem for p in (ROOT / folder).glob("*.py") if p.name != "__init__.py"}
    assert set(package._LAZY.values()) <= inner


def test_the_strategies_map_is_every_value_of_the_enumeration_and_the_extra_built_ins():
    assert sorted(plugins.STRATEGIES) == sorted(ALL_NAMES)


def test_every_registered_text_resolves_to_a_router_strategy():
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar.names("routing_strategy") == sorted(ALL_NAMES)
    for name in ALL_NAMES:
        assert issubclass(registrar.get("routing_strategy", name), RouterStrategy), name


def test_a_text_points_at_the_door_and_never_at_an_inner_file():
    registrar = Registrar()
    plugins.register(registrar)
    for name in ALL_NAMES:
        text = registrar._tables["routing_strategy"][name].target
        module = text.partition(":")[0]
        assert module.count(".") == 3 and module.startswith("skye.router.plugins."), (name, text)


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_folder_imports_no_inner_file(folder):
    """The door alone imports nothing of its folder (``skye.router`` imports the router itself, so
    an empty package stands in for it)."""
    router_dir = ROOT.parent
    code = (
        "import sys, types\n"
        "import skye\n"
        "stub = types.ModuleType('skye.router')\n"
        f"stub.__path__ = [{str(router_dir)!r}]\n"
        "sys.modules['skye.router'] = stub\n"
        f"import skye.router.plugins.{folder}\n"
        f"inner = [m for m in sys.modules if m.startswith('skye.router.plugins.{folder}.')]\n"
        "assert not inner, inner\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_the_default_registrar_loads_the_built_in_strategies():
    from skye.base.plugins import get_registrar

    assert set(ALL_NAMES) <= set(get_registrar().names("routing_strategy"))


def test_lazy_complex_is_not_a_member_of_the_enumeration_and_is_registered():
    assert "lazy_complex" not in NAMES
    assert plugins.IMPLEMENTATIONS[-1] == "lazy_complex"
