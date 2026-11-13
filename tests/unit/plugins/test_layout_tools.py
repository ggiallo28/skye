"""The layout of ``tools/engines`` and ``tools/plugins`` (D110, O80 option D, Requirements 56.9 and
56.10): one folder per MCP client in ``engines`` and one per toolkit in ``plugins``, one door in
each, a ``client.py`` or a ``toolkit.py``."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.base.plugins import Registrar
from skye.tools import engines, plugins

ROOT = Path(plugins.__file__).parent
SKELETONS = [
    "a2a",
    "skyea2a",
]  # folders with a door and a stub class, not registered until O80 is decided
ENGINES_ROOT = Path(engines.__file__).parent
CLIENTS = list(engines.IMPLEMENTATIONS)
TOOLKITS = list(plugins.IMPLEMENTATIONS)
FOLDERS = [*CLIENTS, *TOOLKITS]
PACKAGE = {**dict.fromkeys(CLIENTS, "engines"), **dict.fromkeys(TOOLKITS, "plugins")}
FOLDER_ROOT = {**dict.fromkeys(CLIENTS, ENGINES_ROOT), **dict.fromkeys(TOOLKITS, ROOT)}
MAIN_FILE = {
    "skyemcp": "client.py",
    "fastmcp": "client.py",
    "files": "toolkit.py",
    "openapi": "toolkit.py",
    "human": "toolkit.py",
    "shell": "toolkit.py",
}


def test_the_folders_on_disk_are_the_implementations():
    def on_disk(root):
        return sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != "__pycache__")

    assert (
        on_disk(ENGINES_ROOT)
        == sorted([*CLIENTS, *SKELETONS])
        == ["a2a", "fastmcp", "skyea2a", "skyemcp"]
    )
    assert on_disk(ROOT) == sorted(TOOLKITS) == ["files", "human", "openapi", "shell"]


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_and_its_main_file(folder):
    files = {p.name for p in (FOLDER_ROOT[folder] / folder).iterdir() if p.is_file()}
    assert files == {"__init__.py", MAIN_FILE[folder]}


def test_the_skyemcp_door_resolves_its_class():
    package = importlib.import_module("skye.tools.engines.skyemcp")
    assert set(package._LAZY) == {"SkyeMCPClient"}
    assert package.SkyeMCPClient.__module__ == "skye.tools.engines.skyemcp.client"
    with pytest.raises(AttributeError):
        package.not_a_name  # noqa: B018


def test_the_fastmcp_door_names_its_class_without_importing_fastmcp():
    """Reading the door and the registered text imports neither the inner file nor the library."""
    package = importlib.import_module("skye.tools.engines.fastmcp")
    assert package._LAZY == {"FastMCPClient": "client"}
    registrar = Registrar()
    engines.register(registrar)
    assert (
        registrar._tables["mcp_client"]["fastmcp"].target
        == "skye.tools.engines.fastmcp:FastMCPClient"
    )


def test_every_inner_file_a_door_names_exists():
    for folder in FOLDERS:
        package = importlib.import_module(f"skye.tools.{PACKAGE[folder]}.{folder}")
        assert set(package._LAZY.values()) <= {
            p.stem for p in (FOLDER_ROOT[folder] / folder).glob("*.py")
        }


def test_the_registered_skyemcp_text_resolves_and_the_names_are_both_there():
    registrar = Registrar()
    engines.register(registrar)
    assert registrar.names("mcp_client") == ["fastmcp", "skyemcp"]
    assert registrar.get("mcp_client", "skyemcp").__name__ == "SkyeMCPClient"


def test_the_files_door_resolves_its_class_and_registers_the_toolkit_by_text():
    package = importlib.import_module("skye.tools.plugins.files")
    assert package._LAZY == {"FilesToolkit": "toolkit"}
    assert package.FilesToolkit.__module__ == "skye.tools.plugins.files.toolkit"
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar.names("toolkit") == ["files", "human", "openapi", "shell"]
    assert registrar._tables["toolkit"]["files"].target == "skye.tools.plugins.files:FilesToolkit"
    assert registrar.get("toolkit", "files") is package.FilesToolkit


@pytest.mark.parametrize(
    ("folder", "cls"), [("openapi", "OpenApiToolkit"), ("human", "HumanToolkit")]
)
def test_the_openapi_and_human_doors_resolve_their_class_and_register_by_text(folder, cls):
    package = importlib.import_module(f"skye.tools.plugins.{folder}")
    assert package._LAZY[cls] == "toolkit"
    assert getattr(package, cls).__module__ == f"skye.tools.plugins.{folder}.toolkit"
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar._tables["toolkit"][folder].target == f"skye.tools.plugins.{folder}:{cls}"


def test_a_text_points_at_the_door_and_never_at_an_inner_file():
    registrar = Registrar()
    engines.register(registrar)
    plugins.register(registrar)
    for kind in ("mcp_client", "toolkit"):
        for name in registrar.names(kind):
            module = registrar._tables[kind][name].target.partition(":")[0]
            assert module == f"skye.tools.{PACKAGE[name]}.{name}", (kind, name, module)


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_door_imports_no_inner_file_and_no_fastmcp(folder):
    """The door alone imports nothing of its folder and no vendor library.

    ``skye.tools`` imports the built-in client when it is imported (it is a public name), so the
    subprocess stands an empty package in its place.
    """
    tools_dir = ROOT.parent
    package = PACKAGE[folder]
    code = (
        "import sys, types\n"
        "import skye\n"
        "stub = types.ModuleType('skye.tools')\n"
        f"stub.__path__ = [{str(tools_dir)!r}]\n"
        "sys.modules['skye.tools'] = stub\n"
        f"import skye.tools.{package}.{folder}\n"
        f"inner = [m for m in sys.modules if m.startswith('skye.tools.{package}.{folder}.')]\n"
        "assert not inner, inner\n"
        "assert 'fastmcp' not in sys.modules and 'mcp' not in sys.modules, 'fastmcp was imported'\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_the_old_module_is_gone():
    with pytest.raises(ImportError):
        importlib.import_module("skye.tools.mcp_fastmcp")
    assert not (ROOT.parent / "mcp_fastmcp.py").exists()


def test_the_public_names_did_not_move():
    import skye.tools as tools
    from skye.tools.engines.skyemcp import SkyeMCPClient

    assert tools.SkyeMCPClient is SkyeMCPClient
    assert callable(tools.create_mcp_client)


def test_the_a2a_skeletons_are_not_registered_and_implement_nothing():
    registrar = Registrar()
    engines.register(registrar)
    plugins.register(registrar)
    registered = set(registrar.names("mcp_client")) | set(registrar.names("toolkit"))
    assert not {"a2a", "skyea2a"} & registered
    for folder, cls in (("skyea2a", "SkyeA2AClient"), ("a2a", "A2AClient")):
        package = importlib.import_module(f"skye.tools.engines.{folder}")
        client = getattr(package, cls)("http://agent.example")
        for call in (
            client.describe(),
            client.send_message("hi"),
            client.get_task("t"),
            client.cancel_task("t"),
        ):
            with pytest.raises(NotImplementedError):
                import asyncio

                asyncio.run(call)
