"""The layout of ``auth/plugins`` (D110, Requirements 56.9 and 56.10): one folder per family of credential sources, one door, the same file names."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from skye.auth import plugins
from skye.base.plugins import Registrar

ROOT = Path(plugins.__file__).parent
FOLDERS = list(plugins.IMPLEMENTATIONS)
#: The file names a folder may have: the door, the main code, and the helpers that only the AWS family uses.
ALLOWED_FILES = {"__init__.py", "source.py", "aws_profile.py", "sts.py", "sigv4.py"}
#: Every credential source that ships with ``auth``, as registered before the layout of D110.
SOURCE_NAMES = [
    "anthropic",
    "aws",
    "aws-secrets-manager",
    "aws-ssm",
    "azure",
    "azure-key-vault",
    "bedrock",
    "client-credentials",
    "cohere",
    "google",
    "google-secret-manager",
    "openai",
    "token-exchange",
]


def test_the_folders_on_disk_are_the_implementations():
    on_disk = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert on_disk == sorted(FOLDERS)


@pytest.mark.parametrize("folder", FOLDERS)
def test_a_folder_has_its_door_its_source_and_only_the_known_file_names(folder):
    files = {p.name for p in (ROOT / folder).iterdir() if p.is_file()}
    assert {"__init__.py", "source.py"} <= files
    assert files <= ALLOWED_FILES, sorted(files - ALLOWED_FILES)


def test_what_several_families_use_stays_in_the_root_of_auth():
    root = {p.name for p in ROOT.parent.iterdir() if p.is_file()}
    assert {
        "cache.py",
        "refresh.py",
        "errors.py",
        "rsa_signing.py",
        "registry.py",
        "__init__.py",
    } <= root
    assert not root & {
        "aws.py",
        "azure.py",
        "google.py",
        "oauth2.py",
        "openai_compatible.py",
        "secrets.py",
        "sigv4.py",
        "sts.py",
        "aws_profile.py",
    }


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_resolves(folder):
    door = importlib.import_module(f"skye.auth.plugins.{folder}")
    for name in door._LAZY:
        assert getattr(door, name) is not None, name
    with pytest.raises(AttributeError):
        door.not_a_name  # noqa: B018


@pytest.mark.parametrize("folder", FOLDERS)
def test_every_lazy_name_lives_in_the_source_and_every_source_is_a_lazy_name(folder):
    door = importlib.import_module(f"skye.auth.plugins.{folder}")
    assert set(door._LAZY.values()) == {"source"}
    assert set(door.SOURCES.values()) <= set(door._LAZY)


def test_every_source_name_is_still_registered():
    assert sorted(plugins.SOURCES) == SOURCE_NAMES
    registrar = Registrar()
    plugins.register(registrar)
    assert registrar.names("credential_source") == SOURCE_NAMES


def test_every_registered_text_resolves_and_names_a_door():
    registrar = Registrar()
    plugins.register(registrar)
    for name in SOURCE_NAMES:
        text = registrar._tables["credential_source"][name].target
        module = text.partition(":")[0]
        assert module.count(".") == 3 and module.startswith("skye.auth.plugins."), (
            name,
            text,
        )  # the door, never an inner file
        assert callable(registrar.get("credential_source", name)), name


def test_register_leaves_a_name_that_is_already_registered():
    registrar = Registrar()
    mine = object()
    registrar.credential_source("openai", mine)
    plugins.register(registrar)
    assert registrar.get("credential_source", "openai") is mine
    plugins.register(registrar)  # running it again is harmless
    assert registrar.names("credential_source") == SOURCE_NAMES


@pytest.mark.parametrize("folder", FOLDERS)
def test_importing_a_door_imports_no_inner_file(folder):
    code = (
        "import sys\n"
        f"import skye.auth.plugins.{folder}\n"
        f"inner = [m for m in sys.modules if m.startswith('skye.auth.plugins.{folder}.')]\n"
        "assert not inner, inner\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT.parents[2])},
    )
    assert done.returncode == 0, done.stderr[-800:]


def test_the_public_names_of_skye_auth_did_not_move():
    import skye.auth as auth

    for name in (
        "AwsCredentials",
        "CredentialProvider",
        "SigV4Authenticator",
        "BedrockApiKeyAuthenticator",
        "aws_authenticator",
        "bedrock_authenticator",
    ):
        assert getattr(auth, name) is not None, name
    from skye.auth.plugins.aws import SigV4Authenticator

    assert auth.SigV4Authenticator is SigV4Authenticator


@pytest.mark.parametrize(
    "old",
    [
        "skye.auth.aws",
        "skye.auth.aws_profile",
        "skye.auth.sts",
        "skye.auth.sigv4",
        "skye.auth.google",
        "skye.auth.azure",
        "skye.auth.oauth2",
        "skye.auth.openai_compatible",
        "skye.auth.secrets",
    ],
)
def test_the_old_module_paths_are_gone(old):
    with pytest.raises(ImportError):
        importlib.import_module(old)
