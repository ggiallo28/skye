"""The layout of ``store/plugins`` (D110, Requirements 56.9 and 56.10): one folder per backend, one door, the same file names."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.base.plugins import Registrar
from skye.store import plugins

ROOT = Path(plugins.__file__).parent
FOLDERS = list(plugins.IMPLEMENTATIONS)
ALLOWED_FILES = {"__init__.py", "backend.py"}
NAMES = ["memory", "file", "dynamodb", "redis", "valkey", "postgres", "durable_function"]


def test_the_folders_on_disk_are_the_implementations():
    on_disk = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert on_disk == sorted(FOLDERS)


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_and_only_the_uniform_file_names(folder):
    files = {p.name for p in (ROOT / folder).iterdir() if p.is_file()}
    assert "__init__.py" in files
    assert files <= ALLOWED_FILES, sorted(files - ALLOWED_FILES)


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_resolves_without_its_driver(folder):
    package = importlib.import_module(f"skye.store.plugins.{folder}")
    for name in package._LAZY:
        assert getattr(package, name) is not None, name
    with pytest.raises(AttributeError):
        package.not_a_name  # noqa: B018


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_inner_file_a_door_names_exists(folder):
    package = importlib.import_module(f"skye.store.plugins.{folder}")
    inner = {p.stem for p in (ROOT / folder).glob("*.py") if p.name != "__init__.py"}
    assert set(package._LAZY.values()) <= inner


def test_the_backends_map_is_every_name_of_the_builtin_table():
    assert sorted(plugins.BACKENDS) == sorted(NAMES)
    assert (
        plugins.BACKENDS["valkey"] == plugins.BACKENDS["redis"]
    )  # the same class, a second name (D102)


def test_every_registered_text_resolves():
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar.names("backend") == sorted(NAMES)
    for name in NAMES:
        assert registrar.get("backend", name).__name__.endswith("Backend")


def test_a_text_points_at_the_door_and_never_at_an_inner_file():
    registrar = Registrar()
    plugins.register(registrar)
    for name in NAMES:
        text = registrar._tables["backend"][name].target
        module = text.partition(":")[0]
        assert module.count(".") == 3 and module.startswith("skye.store.plugins."), (name, text)


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_folder_imports_no_inner_file_and_no_driver(folder):
    """The door alone imports nothing of its folder and no driver (``skye.store`` imports the classes itself, so an empty package stands in for it)."""
    store_dir = ROOT.parent
    code = (
        "import sys, types\n"
        "import skye\n"
        "stub = types.ModuleType('skye.store')\n"
        f"stub.__path__ = [{str(store_dir)!r}]\n"
        "sys.modules['skye.store'] = stub\n"
        f"import skye.store.plugins.{folder}\n"
        f"inner = [m for m in sys.modules if m.startswith('skye.store.plugins.{folder}.')]\n"
        "assert not inner, inner\n"
        "assert not {'boto3', 'botocore', 'redis', 'valkey', 'pg8000', 'asyncpg'} & set(sys.modules), 'a driver was imported'\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_the_old_module_paths_are_gone():
    for name in ("memory", "file", "dynamodb", "redis", "postgres", "durable_function"):
        with pytest.raises(ImportError):
            importlib.import_module(f"skye.store.{name}")


def test_the_public_names_did_not_move():
    import skye.store as store

    for name in (
        "InMemoryBackend",
        "FileSystemBackend",
        "DynamoDBBackend",
        "RedisBackend",
        "PostgreSQLBackend",
        "DurableFunctionBackend",
        "backend",
        "register_backend",
        "check_backend",
    ):
        assert hasattr(store, name), name
