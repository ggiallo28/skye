"""The layout of ``models/plugins`` (D110, Requirements 56.9 and 56.10): one folder per provider,
one door, the same file names."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.base.plugins import Registrar
from skye.models import plugins

ROOT = Path(plugins.__file__).parent
FOLDERS = list(plugins.IMPLEMENTATIONS)
#: The file names a folder may have (the same in every folder).
ALLOWED_FILES = {
    "request.py",
    "response.py",
    "capabilities.py",
    "errors.py",
    "schema.py",
    "__init__.py",
    "provider.py",
    "embeddings.py",
    "multimodal_embeddings.py",
    "decision.py",
    "profile.toml",
    "profile_multimodal.toml",
}


def test_the_folders_on_disk_are_the_implementations():
    on_disk = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert on_disk == sorted(FOLDERS)


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_and_only_the_uniform_file_names(folder):
    files = {p.name for p in (ROOT / folder).iterdir() if p.is_file()}
    assert "__init__.py" in files
    assert files <= ALLOWED_FILES, sorted(files - ALLOWED_FILES)


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_resolves(folder):
    package = importlib.import_module(f"skye.models.plugins.{folder}")
    for name in package._LAZY:
        assert getattr(package, name) is not None, name
    with pytest.raises(AttributeError):
        package.not_a_name  # noqa: B018


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_inner_file_is_offered_by_the_door(folder):
    """Every file a door names exists, and the folder has no other code file than the uniform names
    (the helpers are not offered by the door)."""
    package = importlib.import_module(f"skye.models.plugins.{folder}")
    inner = {p.stem for p in (ROOT / folder).glob("*.py") if p.name != "__init__.py"}
    assert set(package._LAZY.values()) <= inner


def test_every_registered_text_resolves():
    registrar = Registrar()
    plugins.register(registrar)
    resolved: dict[tuple[str, str, str | None], object] = {
        ("provider", name, function): registrar.get("provider", name, function)
        for function in ("model", "embedding", "decision")
        for name in registrar.names("provider", function)
    }
    resolved.update(
        {
            ("tokenizer", name, None): registrar.get("tokenizer", name)
            for name in registrar.names("tokenizer")
        }
    )
    assert (
        len(resolved) == 12
    )  # 5 model providers, 5 embedding providers, 1 decision model, 1 tokenizer
    assert ("provider", "jev", "decision") in resolved


def test_a_text_points_at_the_door_and_never_at_an_inner_file():
    registrar = Registrar()
    plugins.register(registrar)
    for function in ("model", "embedding", "decision"):
        for name in registrar.names("provider", function):
            text = registrar._tables["provider"][(name, function)].target
            module = text.partition(":")[0]
            assert module.count(".") == 3 and module.startswith("skye.models.plugins."), (
                function,
                name,
                text,
            )


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_folder_imports_no_inner_file(folder):
    """The door alone imports nothing of its folder and no vendor library.

    ``skye.models`` itself imports the public classes when it is imported, so the subprocess stands
    an empty package in its place: that isolates the door.
    """
    models_dir = ROOT.parent
    code = (
        "import sys, types\n"
        "import skye\n"
        "stub = types.ModuleType('skye.models')\n"
        f"stub.__path__ = [{str(models_dir)!r}]\n"
        "sys.modules['skye.models'] = stub\n"
        f"import skye.models.plugins.{folder}\n"
        f"inner = [m for m in sys.modules if m.startswith('skye.models.plugins.{folder}.')]\n"
        "assert not inner, inner\n"
        "assert not {'openai', 'anthropic', 'boto3', 'tiktoken'} & set(sys.modules), "
        "'a vendor library was imported'\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_a_missing_inner_file_breaks_only_its_own_name(tmp_path, monkeypatch):
    """The door resolves a name from its inner file only when asked: a missing file is an
    ImportError on that name alone."""
    from skye.base.lazy_import import lazy_names

    package = tmp_path / "demo_door"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "present.py").write_text("class Here: ...\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    door = importlib.import_module("demo_door")
    door.__getattr__ = lazy_names("demo_door", {"Here": "present", "Gone": "absent"})
    assert door.__getattr__("Here").__name__ == "Here"
    with pytest.raises(ImportError):
        door.__getattr__("Gone")


def test_a_missing_profile_file_is_a_configuration_error_naming_the_file():
    from skye.base.exceptions import ConfigurationError
    from skye.models.utilities.vendor import read_profile

    with pytest.raises(ConfigurationError) as caught:
        read_profile("skye.models.plugins.openai", "no_such_profile.toml")
    assert "no_such_profile.toml" in str(caught.value)


# -- models/utilities: what a plugin is written with (D110)
# -----------------------------------------------------------

UTILITIES = ROOT.parent / "utilities"


def test_the_utilities_are_plain_files_and_the_two_wire_format_providers():
    """``plugins`` does not list them, because they are not providers; the classes of the component
    itself are in its root."""
    names = sorted(p.name for p in UTILITIES.iterdir() if p.name not in {"__pycache__"})
    assert names == [
        "__init__.py",
        "anthropic_compatible",
        "blocking.py",
        "capability_choice.py",
        "credentials.py",
        "error_mapping.py",
        "eventstream.py",
        "multimodal.py",
        "openai_compatible",
        "prompt_parts.py",
        "rest.py",
        "retry.py",
        "schema_check.py",
        "streaming.py",
        "structured.py",
        "vendor.py",
    ]
    assert not set(names) & set(plugins.IMPLEMENTATIONS)
    root = {p.name for p in UTILITIES.parent.iterdir() if p.is_file()}
    assert {"base.py", "cost.py", "token_counter.py", "registry.py", "decision.py"} <= root


@pytest.mark.parametrize("base", ["openai_compatible", "anthropic_compatible"])
def test_a_wire_format_base_has_the_uniform_file_names(base):
    files = {p.name for p in (UTILITIES / base).iterdir() if p.is_file()}
    assert files == {"__init__.py", "provider.py", "request.py", "response.py", "capabilities.py"}


def test_the_public_names_did_not_move():
    import skye.models as models

    for name in (
        "BaseModelProvider",
        "BaseEmbeddingProvider",
        "OpenAICompatibleProvider",
        "CostCalculator",
        "TokenCounter",
        "post_json",
    ):
        assert hasattr(models, name), name
    from skye.models.utilities.openai_compatible import OpenAICompatibleProvider

    assert models.OpenAICompatibleProvider is OpenAICompatibleProvider


def test_the_old_paths_are_gone():
    for old in (
        "skye.models.transport",
        "skye.models.utilities.transport",
        "skye.models.utilities.base",
        "skye.models.utilities.http",
        "skye.models.utilities.payload",
        "skye.models.utilities.accounting",
        "skye.models.openai_compatible",
        "skye.models.anthropic_compatible",
        "skye.models.llm",
        "skye.models.embeddings",
    ):
        with pytest.raises(ImportError):
            importlib.import_module(old)
