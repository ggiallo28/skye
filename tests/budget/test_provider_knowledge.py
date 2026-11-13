"""What a built-in provider knows is written in its adapter and its profile only (task 6.8,
Requirement 60.8).

A static (AST) rule over ``src/skye``. A string constant (docstrings are documentation and are left
out) fails the test when it is, outside
the folder of the provider that owns it (``models/plugins/<folder>/``, adapter and profile):

1. the name of a built-in provider (``"openai"``, ``"bedrock"``, ...);
2. a variable that holds the API key of a provider (``"OPENAI_API_KEY"``, ...);
3. the id of a model that has a price in a profile (``"gpt-4o"``, ...): a price is data of the
   profile, and the id is how code would look it up.

None of the three is listed here. They are read from ``models/plugins/*/profile.toml``, so a
provider that is added is covered when its profile
is written. The folder that owns a name is the folder of the profile that holds it. ``KNOWN`` lists
the files that still write one of them, each
with the reason; an entry only goes away: the test fails when a listed file no longer needs it. The
scanner only sees an exact string, so a
name built from parts or read from a file is not seen.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from tests.budget.measure import ROOT

SRC = ROOT / "src" / "skye"
PLUGINS = SRC / "models" / "plugins"

# : Files that write a name of a built-in provider outside its folder, with the reason. The list
# only shrinks.
KNOWN: dict[str, str] = {
    "auth/plugins/__init__.py": "registers the Azure and Google credential sources by the name of "
    "their provider",
    "auth/plugins/aws/__init__.py": "asks for the AWS region variables through the provider name "
    "`bedrock` (task 6.6)",
    "auth/plugins/aws/source.py": "asks for the AWS region variables through the provider name "
    "`bedrock` (task 6.6)",
    "auth/plugins/aws/sts.py": "asks for the AWS region variables through the provider name "
    "`bedrock` (task 6.6)",
    "auth/plugins/azure/__init__.py": "credential source of the Azure provider, named after it",
    "auth/plugins/azure/source.py": "credential source of the Azure provider: its name and its key "
    "variable (tied to the profile by a test)",
    "auth/plugins/google/__init__.py": "credential source of the Google provider, named after it",
    "auth/plugins/google/source.py": "credential source of the Google provider: its name and its "
    "key variable (tied to the profile by a test)",
    "auth/plugins/openai_compatible/__init__.py": "credential source for the providers that take a "
    "bearer key, by their names",
    "auth/plugins/openai_compatible/source.py": "credential source for the providers that take a "
    "bearer key, by their names",
    "auth/plugins/secrets/source.py": "reads the secret of the Azure and Google providers, by "
    "their names",
    "models/plugins/__init__.py": "the list of the built-in providers that registers each one by "
    "name",
    "models/utilities/credentials.py": "asks for the AWS region variables through the provider "
    "name `bedrock` (task 6.6)",
    "models/utilities/eventstream.py": "the default `provider` of the event-stream decoder (an "
    "error label), the Bedrock wire format",
    "models/utilities/multimodal.py": (
        "`to_bedrock_format` labels its errors with the provider name"
    ),
    "store/plugins/dynamodb/backend.py": "asks for the AWS region variables through the provider "
    "name `bedrock` (task 6.6)",
    "store/plugins/postgres/backend.py": "asks for the AWS region variables through the provider "
    "name `bedrock` (task 6.6)",
}


def knowledge() -> dict[str, tuple[str, str]]:
    """Every name a profile owns: ``{literal: (kind, owner folder)}``, from
    ``models/plugins/*/profile.toml``."""
    found: dict[str, tuple[str, str]] = {}
    for path in sorted(PLUGINS.glob("*/profile.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        folder = path.parent.name
        found.setdefault(data["name"], ("provider name", folder))
        for variable in data.get("api_key_variables", ()):
            found.setdefault(variable, ("key variable", folder))
        for model, fields in data.get("models", {}).items():
            if "prompt_price" in fields or "completion_price" in fields:
                found.setdefault(model, ("priced model", folder))
    return found


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def literals_in(
    source: str, names: dict[str, tuple[str, str]], own: str | None
) -> list[tuple[int, str, str]]:
    """The string constants of ``source`` that a profile owns, outside the docstrings and outside
    the folder ``own``: ``(line, value, kind)``."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    return [
        (node.lineno, node.value, names[node.value][0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and node.value in names
        and names[node.value][1] != own
    ]


def folder_of(path: Path) -> str | None:
    """The provider folder a source file lives in (``models/plugins/<folder>/``), or ``None``."""
    parts = path.relative_to(SRC).parts
    return parts[2] if parts[:2] == ("models", "plugins") and len(parts) > 3 else None


def scan() -> dict[str, list[tuple[int, str, str]]]:
    names = knowledge()
    found = {
        path.relative_to(SRC).as_posix(): literals_in(
            path.read_text(encoding="utf-8"), names, folder_of(path)
        )
        for path in sorted(SRC.rglob("*.py"))
    }
    return {file: hits for file, hits in found.items() if hits}


def test_the_profiles_name_every_built_in_provider() -> None:
    names = knowledge()
    folders = {path.parent.name for path in PLUGINS.glob("*/profile.toml")}
    assert {"openai", "anthropic", "bedrock", "google", "azure", "cohere"} <= folders
    assert {kind for kind, _ in names.values()} == {"provider name", "key variable", "priced model"}


def test_no_file_writes_what_a_profile_owns_outside_its_provider_folder() -> None:
    found = {file: hits for file, hits in scan().items() if file not in KNOWN}
    assert not found, (
        "a provider name, a key variable or a priced model id is written outside the folder of its "
        f"provider; read it from the profile instead: {found}"
    )


def test_the_known_files_still_need_their_entry() -> None:
    now = scan()
    stale = [file for file in KNOWN if file not in now]
    assert not stale, f"nothing is left in these files, remove them from KNOWN: {stale}"


def test_the_scanner_finds_a_name_and_leaves_the_owner_a_docstring_and_other_text_alone() -> None:
    names = {
        "openai": ("provider name", "openai"),
        "OPENAI_API_KEY": ("key variable", "openai"),
        "gpt-4": ("priced model", "openai"),
    }
    code = (
        '"""The ``openai`` provider."""\n\nKEY = "OPENAI_API_KEY"\nMODEL = "gpt-4"\nOTHER = '
        '"my-model"\n\n\ndef f(name="openai"):\n    return name\n'
    )
    assert literals_in(code, names, "bedrock") == [
        (3, "OPENAI_API_KEY", "key variable"),
        (4, "gpt-4", "priced model"),
        (8, "openai", "provider name"),
    ]
    assert literals_in(code, names, "openai") == []  # the folder that owns the names may write them
    assert (
        literals_in('x = "OpenAI"\ny = "openai-compatible"\n', names, None) == []
    )  # exact strings only
