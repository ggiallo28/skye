"""The layout of ``agents/plugins`` (D110): one folder per agent type, one door."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.agents import plugins
from skye.base.plugins import Registrar

ROOT = Path(plugins.__file__).parent
FOLDERS = list(plugins.IMPLEMENTATIONS)


def test_the_folders_on_disk_are_the_implementations():
    assert sorted(
        p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__"
    ) == sorted(FOLDERS)


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_and_the_agent_file(folder):
    assert {p.name for p in (ROOT / folder).iterdir() if p.is_file()} == {"__init__.py", "agent.py"}


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_resolves(folder):
    package = importlib.import_module(f"skye.agents.plugins.{folder}")
    for name in package._LAZY:
        assert getattr(package, name) is not None


def test_every_registered_text_resolves_and_points_at_the_door():
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar.names("agent") == ["react"]
    assert registrar._tables["agent"]["react"].target == "skye.agents.plugins.react:ReActAgent"
    assert registrar.get("agent", "react").__name__ == "ReActAgent"


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_door_imports_no_inner_file(folder):
    agents_dir = ROOT.parent
    code = (
        "import sys, types\n"
        "import skye\n"
        "stub = types.ModuleType('skye.agents')\n"
        f"stub.__path__ = [{str(agents_dir)!r}]\n"
        "sys.modules['skye.agents'] = stub\n"
        f"import skye.agents.plugins.{folder}\n"
        f"assert not [m for m in sys.modules if m.startswith('skye.agents.plugins.{folder}.')]\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-600:]


def test_import_agents_registers_nothing_in_the_default_registrar():
    code = (
        "import skye.agents\n"
        "from skye.base import plugins\n"
        "assert plugins._default is None or not plugins._default._builtins_loaded, "
        "'a built-in plugin was loaded by import skye.agents'\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-600:]
