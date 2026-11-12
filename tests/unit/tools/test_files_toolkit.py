"""The built-in toolkit ``files`` (task 19.1, Requirement 62.7): registered by text, read-only, and kept inside its root."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import skye
from skye.base.exceptions import ValidationError
from skye.base.messages import CapabilityStatus
from skye.completion import CapabilityCall
from skye.tools.plugins.files import FilesToolkit


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small tree: ``notes.txt``, ``src/app.py``, ``.secret`` and an empty ``docs/``."""
    (tmp_path / "notes.txt").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / ".secret").write_text("token", encoding="utf-8")
    return tmp_path


async def call(toolkit: FilesToolkit, name: str, **arguments: object):
    return await toolkit.run(CapabilityCall(id="1", name=f"files.{name}", arguments=arguments))


def snapshot(folder: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in folder.rglob("*")
    )


# -- registration -------------------------------------------------------------------------------------------------------


def test_the_toolkit_is_registered_as_files_and_built_by_name(tree: Path):
    assert "files" in skye.Plugins().names("toolkit")
    toolkit = skye.toolkit("files", root=tree)
    assert isinstance(toolkit, FilesToolkit)
    assert toolkit.toolkit_name == "files"
    assert skye.Plugins().get("toolkit", "files") is FilesToolkit


def test_a_registrar_with_the_tools_door_gets_the_text_target():
    from skye.base.plugins import Registrar
    from skye.tools import plugins

    registrar = Registrar()
    plugins.register(registrar)
    assert registrar._tables["toolkit"]["files"].target == "skye.tools.plugins.files:FilesToolkit"


# -- the options --------------------------------------------------------------------------------------------------------


def test_the_option_root_is_required():
    with pytest.raises(ValidationError) as caught:
        FilesToolkit()
    assert "root" in str(caught.value)
    with pytest.raises(ValidationError):
        skye.toolkit("files")


def test_root_must_be_a_folder(tree: Path):
    with pytest.raises(ValidationError):
        FilesToolkit(root=tree / "notes.txt")
    with pytest.raises(ValidationError):
        FilesToolkit(root=tree / "missing")


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "10"])
def test_max_bytes_must_be_a_positive_number(tree: Path, value):
    with pytest.raises(ValidationError):
        FilesToolkit(root=tree, max_bytes=value)


def test_root_accepts_text_and_a_path(tree: Path):
    assert (
        FilesToolkit(root=str(tree)).list_files.execute()
        == FilesToolkit(root=tree).list_files.execute()
    )


# -- list_files and read_file -------------------------------------------------------------------------------------------


async def test_list_files_returns_sorted_names_and_marks_folders(tree: Path):
    toolkit = FilesToolkit(root=tree)
    assert toolkit.list_files.execute() == ["docs/", "notes.txt", "src/"]
    assert toolkit.list_files.execute(path="src") == ["app.py"]
    assert toolkit.list_files.execute(path=".") == toolkit.list_files.execute()


async def test_read_file_returns_the_text(tree: Path):
    toolkit = FilesToolkit(root=tree)
    assert toolkit.read_file.execute(path="notes.txt") == "hello\nworld\n"
    assert toolkit.read_file.execute(path="src/app.py") == "print('hi')\n"
    assert (
        toolkit.read_file.execute(path="src/../notes.txt") == "hello\nworld\n"
    )  # a ".." that stays inside


async def test_a_run_by_the_prefixed_name_gives_an_ok_message(tree: Path):
    toolkit = FilesToolkit(root=tree)
    message = await call(toolkit, "read_file", path="notes.txt")
    assert message.status is CapabilityStatus.OK
    assert message.content == "hello\nworld\n"
    listing = await call(toolkit, "list_files")
    assert listing.status is CapabilityStatus.OK
    assert "notes.txt" in listing.content


async def test_hidden_entries_are_left_out_and_refused_unless_asked_for(tree: Path):
    toolkit = FilesToolkit(root=tree)
    assert ".secret" not in toolkit.list_files.execute()
    refused = await call(toolkit, "read_file", path=".secret")
    assert refused.status is CapabilityStatus.ERROR
    assert "hidden" in refused.content
    shown = FilesToolkit(root=tree, include_hidden=True)
    assert ".secret" in shown.list_files.execute()
    assert shown.read_file.execute(path=".secret") == "token"


async def test_a_long_listing_is_cut_and_says_so(tmp_path: Path):
    for number in range(520):
        (tmp_path / f"f{number:04d}.txt").write_text("x")
    names = FilesToolkit(root=tmp_path).list_files.execute()
    assert len(names) == 501
    assert names[0] == "f0000.txt" and names[499] == "f0499.txt"
    assert names[-1] == "[20 more entries not shown]"


async def test_a_long_file_is_cut_and_says_so(tmp_path: Path):
    (tmp_path / "big.txt").write_text("a" * 1000)
    text = FilesToolkit(root=tmp_path, max_bytes=100).read_file.execute(path="big.txt")
    assert text.startswith("a" * 100 + "\n[cut: ")
    assert "first 100 of 1000 bytes" in text
    assert text.split("\n")[0] == "a" * 100


async def test_a_file_that_fits_has_no_marker(tmp_path: Path):
    (tmp_path / "ok.txt").write_text("a" * 100)
    assert FilesToolkit(root=tmp_path, max_bytes=100).read_file.execute(path="ok.txt") == "a" * 100


async def test_a_cut_inside_a_character_is_not_an_error(tmp_path: Path):
    (tmp_path / "wide.txt").write_text("é" * 100, encoding="utf-8")  # two bytes each
    text = FilesToolkit(root=tmp_path, max_bytes=101).read_file.execute(path="wide.txt")
    assert text.startswith("é" * 50 + "\n[cut: ")


async def test_a_binary_file_is_refused(tmp_path: Path):
    (tmp_path / "data.bin").write_bytes(b"abc\x00def")
    (tmp_path / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
    toolkit = FilesToolkit(root=tmp_path)
    for name in ("data.bin", "latin.txt"):
        message = await call(toolkit, "read_file", path=name)
        assert message.status is CapabilityStatus.ERROR
        assert "text file" in message.content


async def test_a_folder_given_to_read_file_and_a_file_given_to_list_files_are_clear_errors(
    tree: Path,
):
    toolkit = FilesToolkit(root=tree)
    folder = await call(toolkit, "read_file", path="src")
    assert folder.status is CapabilityStatus.ERROR and "list_files" in folder.content
    file = await call(toolkit, "list_files", path="notes.txt")
    assert file.status is CapabilityStatus.ERROR and "read_file" in file.content
    missing = await call(toolkit, "read_file", path="nothing.txt")
    assert missing.status is CapabilityStatus.ERROR and "does not exist" in missing.content


# -- containment --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "\\Windows\\win.ini",
        "C:\\Windows\\win.ini",
        "C:win.ini",
        "\\\\server\\share\\x",
        "../outside.txt",
        "src/../../outside.txt",
        "..",
        "a\x00b",
    ],
)
async def test_a_path_that_leaves_the_root_is_refused(tree: Path, path: str):
    (tree.parent / "outside.txt").write_text("secret")
    toolkit = FilesToolkit(root=tree)
    for name in ("read_file", "list_files"):
        message = await call(toolkit, name, path=path)
        assert message.status is CapabilityStatus.ERROR, (name, path)
        assert "secret" not in message.content
        assert str(tree.parent) not in message.content  # the real path outside is never named


async def test_a_sibling_folder_with_the_same_prefix_is_refused(tmp_path: Path):
    root = tmp_path / "project"
    other = tmp_path / "project-other"
    root.mkdir()
    other.mkdir()
    (other / "x.txt").write_text("secret")
    toolkit = FilesToolkit(root=root)
    message = await call(toolkit, "read_file", path="../project-other/x.txt")
    assert message.status is CapabilityStatus.ERROR
    assert "secret" not in message.content


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links on this platform")
async def test_a_link_that_points_outside_is_refused(tmp_path: Path):
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "x.txt").write_text("secret")
    try:
        (root / "file-link").symlink_to(outside / "x.txt")
        (root / "folder-link").symlink_to(outside, target_is_directory=True)
        (root / "inside-link").symlink_to(root / "real.txt")
    except OSError:
        pytest.skip("symbolic links are not allowed here")
    (root / "real.txt").write_text("fine")
    toolkit = FilesToolkit(root=root)
    for path in ("file-link", "folder-link/x.txt"):
        message = await call(toolkit, "read_file", path=path)
        assert message.status is CapabilityStatus.ERROR, path
        assert "secret" not in message.content
    assert (await call(toolkit, "list_files", path="folder-link")).status is CapabilityStatus.ERROR
    assert (
        toolkit.read_file.execute(path="inside-link") == "fine"
    )  # a link that stays inside is allowed


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links on this platform")
async def test_a_root_that_is_a_link_is_resolved_once(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "x.txt").write_text("ok")
    try:
        (tmp_path / "link").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not allowed here")
    assert FilesToolkit(root=tmp_path / "link").read_file.execute(path="x.txt") == "ok"


# -- read only, schemas, errors -----------------------------------------------------------------------------------------


async def test_nothing_is_written_by_any_call(tree: Path):
    before = snapshot(tree)
    toolkit = FilesToolkit(root=tree)
    for name, arguments in [
        ("list_files", {}),
        ("list_files", {"path": "src"}),
        ("read_file", {"path": "notes.txt"}),
        ("read_file", {"path": "../x"}),
        ("read_file", {"path": ".secret"}),
        ("read_file", {"path": "src"}),
    ]:
        await call(toolkit, name, **arguments)
    assert snapshot(tree) == before
    assert {schema.name for schema in await toolkit.list_schemas()} == {
        "files.list_files",
        "files.read_file",
    }


async def test_the_schemas_carry_the_prefix_and_have_no_self(tree: Path):
    schemas = {s.name: s for s in await FilesToolkit(root=tree).list_schemas()}
    assert set(schemas) == {"files.list_files", "files.read_file"}
    for schema in schemas.values():
        assert "self" not in schema.parameters["properties"]
        assert schema.description
    assert schemas["files.read_file"].parameters["required"] == ["path"]
    assert (
        "required" not in schemas["files.list_files"].parameters
        or not schemas["files.list_files"].parameters["required"]
    )


async def test_a_failing_call_is_an_error_message_and_not_an_exception(tree: Path):
    message = await call(FilesToolkit(root=tree), "read_file", path="../../etc/passwd")
    assert message.status is CapabilityStatus.ERROR
    assert message.content.startswith("Error: ")
    unknown = await call(FilesToolkit(root=tree), "delete_file", path="notes.txt")
    assert unknown.status is CapabilityStatus.ERROR
    wrong_type = await call(FilesToolkit(root=tree), "read_file", path=5)
    assert wrong_type.status is CapabilityStatus.ERROR


async def test_the_built_toolkit_takes_an_alias(tree: Path):
    toolkit = skye.toolkit("files", alias="docs-files", root=tree)
    names = {s.name for s in await toolkit.list_schemas()}
    assert names == {"docs-files.list_files", "docs-files.read_file"}


async def test_two_toolkits_keep_their_own_root(
    tree: Path, tmp_path_factory: pytest.TempPathFactory
):
    other = tmp_path_factory.mktemp("other")
    (other / "only-here.txt").write_text("x")
    first, second = FilesToolkit(root=tree), FilesToolkit(root=other)
    assert "only-here.txt" in second.list_files.execute()
    assert "only-here.txt" not in first.list_files.execute()


# -- loading ------------------------------------------------------------------------------------------------------------


def test_importing_skye_tools_does_not_import_the_file_system_code():
    code = (
        "import sys\n"
        "import skye.tools\n"
        "import skye.tools.plugins\n"
        "assert 'skye.tools.plugins.files.toolkit' not in sys.modules, 'imported with skye.tools'\n"
        "from skye.base.plugins import get_registrar\n"
        "assert 'files' in get_registrar().names('toolkit')\n"
        "assert 'skye.tools.plugins.files.toolkit' not in sys.modules, 'imported at registration'\n"
        "get_registrar().get('toolkit', 'files')\n"
        "assert 'skye.tools.plugins.files.toolkit' in sys.modules, 'not imported when asked for'\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
