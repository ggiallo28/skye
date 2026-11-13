"""The seam for the skills (Requirement 62.8): a ``SKILL.md`` given to an agent adds the toolkit
``files`` for its folder."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from skye.agents import skills
from skye.agents.registry import REACT, create_agent
from skye.agents.skills import skill_folder, skill_toolkits
from skye.base.exceptions import ConfigurationError
from skye.base.messages import CapabilityStatus
from skye.base.plugins import Registrar
from skye.completion import CapabilityCall


def _make_skill(root: Path, name: str, text: str = "# skill") -> Path:
    folder = root / name
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(text)
    (folder / "references" / "a.md").write_text("reference text")
    (root / "outside.txt").write_text("secret")
    return folder


def test_a_skill_file_or_its_folder_gives_the_folder(tmp_path):
    folder = _make_skill(tmp_path, "refund")
    assert skill_folder(folder / "SKILL.md") == folder.resolve()
    assert skill_folder(folder) == folder.resolve()


def test_a_path_that_is_not_a_skill_raises(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "notes.md").write_text("x")
    for bad in (tmp_path / "plain", tmp_path / "notes.md", tmp_path / "missing" / "SKILL.md"):
        with pytest.raises(ConfigurationError):
            skill_folder(bad)


def test_no_skill_resolves_nothing_even_without_the_toolkit():
    assert skill_toolkits([], registrar=Registrar()) == []


def test_without_a_files_toolkit_the_error_lists_the_names(tmp_path):
    folder = _make_skill(tmp_path, "refund")
    with pytest.raises(ConfigurationError):
        skill_toolkits([folder / "SKILL.md"], registrar=Registrar())


def test_the_toolkit_is_the_registered_one_limited_to_the_folder(tmp_path):
    folder = _make_skill(tmp_path, "refund")
    seen = []

    class Fake:
        def __init__(self, *, roots):
            seen.append(roots)

    registrar = Registrar()
    registrar.toolkit("files", Fake)
    skill_toolkits([folder / "SKILL.md"], registrar=registrar)
    assert seen == [[folder.resolve()]]  # one skill is also given as roots


def test_several_skills_build_one_toolkit_with_all_the_folders(tmp_path):
    first = _make_skill(tmp_path / "a", "refund")
    second = _make_skill(tmp_path / "b", "refund")
    seen = []

    class Fake:
        def __init__(self, **options):
            seen.append(options)

    registrar = Registrar()
    registrar.toolkit("files", Fake)
    toolkits = skill_toolkits([first, second, first / "SKILL.md"], registrar=registrar)
    assert len(toolkits) == 1 and seen == [
        {"roots": [first.resolve(), second.resolve()]}
    ]  # a repeated folder is read once


def test_a_hundred_skills_build_one_instance_with_two_tools(tmp_path):
    skills_ = [_make_skill(tmp_path / f"s{n}", "skill") for n in range(100)]
    (toolkit,) = skill_toolkits(skills_)
    names = toolkit.list_files.execute()
    assert (
        len(names) == 100 and len(set(names)) == 100
    )  # the same folder name, a number to tell them apart


@pytest.mark.asyncio
async def test_the_real_files_toolkit_reads_the_skill_and_nothing_outside(tmp_path):
    folder = _make_skill(tmp_path, "refund")
    (toolkit,) = skill_toolkits([folder / "SKILL.md"])
    names = [schema.name for schema in await toolkit.list_schemas()]
    assert names == ["files.list_files", "files.read_file"]
    read = await toolkit.run(
        CapabilityCall(id="1", name="files.read_file", arguments={"path": "refund/references/a.md"})
    )
    assert read.status is CapabilityStatus.OK and "reference text" in read.content
    outside = await toolkit.run(
        CapabilityCall(id="2", name="files.read_file", arguments={"path": "refund/../outside.txt"})
    )
    assert outside.status is CapabilityStatus.ERROR and "secret" not in outside.content


def test_an_agent_given_a_skill_holds_the_toolkit_and_one_without_does_not(tmp_path):
    folder = _make_skill(tmp_path, "refund")
    agent = create_agent(REACT, skills=[str(folder / "SKILL.md")])
    assert len(agent.skill_toolkits) == 1
    assert create_agent(REACT).skill_toolkits == []


def test_the_module_never_imports_tools():
    tree = ast.parse(Path(skills.__file__).read_text())
    imported = [
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    ]
    assert not [m for m in imported if m and m.startswith("skye.tools")]


def test_importing_the_module_does_not_load_tools():
    code = "import sys, skye.agents.skills; sys.exit(1 if 'skye.tools' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
