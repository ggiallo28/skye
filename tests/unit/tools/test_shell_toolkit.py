"""The built-in toolkit ``shell`` (base): opt-in, no shell, allow list, time limit and cut."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from skye.base.exceptions import CapabilityError, ValidationError
from skye.base.messages import CapabilityStatus
from skye.base.plugins import Registrar
from skye.completion import CapabilityCall
from skye.tools.plugins import shell
from skye.tools.plugins.shell import ShellToolkit

posix = pytest.mark.skipif(os.name != "posix", reason="uses POSIX programs")


def test_the_options_and_their_errors(tmp_path: Path):
    for bad in (None, [], "echo", [""], ["bin/echo"], ["a\\b"], [3]):
        with pytest.raises(ValidationError) as caught:
            ShellToolkit(allow=bad)  # type: ignore[arg-type]
        assert caught.value.details["field"] == "allow"
    with pytest.raises(ValidationError):
        ShellToolkit(allow=["echo"], cwd=tmp_path / "missing")
    for timeout in (0, -1, True):
        with pytest.raises(ValidationError):
            ShellToolkit(allow=["echo"], timeout=timeout)
    for max_bytes in (0, True, 1.5):
        with pytest.raises(ValidationError):
            ShellToolkit(allow=["echo"], max_bytes=max_bytes)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_schema_has_the_prefix_and_no_self():
    schemas = await ShellToolkit(allow=["echo"]).list_schemas()
    assert [s.name for s in schemas] == ["shell.run_command"]
    assert "self" not in schemas[0].parameters["properties"]
    assert schemas[0].parameters["required"] == ["command"]


@posix
def test_an_allowed_program_runs():
    assert (
        ShellToolkit(allow=["echo"]).run_command.execute(command="echo hello")
        == "exit code 0\nhello\n"
    )


@posix
def test_the_exit_code_and_stderr_are_shown(tmp_path: Path):
    text = ShellToolkit(allow=["ls"]).run_command.execute(command=f"ls {tmp_path / 'missing'}")
    assert text.startswith("exit code ") and not text.startswith("exit code 0")
    assert "--- stderr ---" in text


@posix
def test_a_program_that_is_not_allowed_is_refused_and_the_error_lists_the_allowed_ones():
    toolkit = ShellToolkit(allow=["echo", "ls"])
    with pytest.raises(CapabilityError) as caught:
        toolkit.run_command.execute(command="rm -rf x")
    assert "'rm' is not allowed" in str(caught.value) and "echo, ls" in str(caught.value)
    with pytest.raises(CapabilityError, match="allowed programs are: echo, ls"):
        toolkit.run_command.execute(command="   ")
    with pytest.raises(CapabilityError, match="cannot be split"):
        toolkit.run_command.execute(command='echo "open')
    with pytest.raises(CapabilityError, match="is not allowed"):
        toolkit.run_command.execute(command="/bin/echo hi")  # a path is not an allowed name


def test_a_program_that_is_allowed_but_missing_is_an_error():
    with pytest.raises(CapabilityError, match="was not found"):
        ShellToolkit(allow=["definitely-not-a-program-xyz"]).run_command.execute(
            command="definitely-not-a-program-xyz"
        )


@posix
def test_no_shell_is_used():
    toolkit = ShellToolkit(allow=["echo"])
    assert toolkit.run_command.execute(command="echo a; echo b | cat > x") == (
        "exit code 0\na; echo b | cat > x\n"
    )
    assert toolkit.run_command.execute(command="echo $HOME $(id)") == "exit code 0\n$HOME $(id)\n"


@posix
def test_the_time_limit_kills_the_process():
    toolkit = ShellToolkit(allow=["sleep"], timeout=0.3)
    started = time.monotonic()
    with pytest.raises(CapabilityError, match="did not finish in 0.3 seconds"):
        toolkit.run_command.execute(command="sleep 10")
    assert time.monotonic() - started < 5


@posix
def test_a_long_output_is_cut_with_a_marker():
    text = ShellToolkit(allow=["printf"], max_bytes=50).run_command.execute(
        command="printf %0200d 0"
    )
    assert "[cut: the first 50 of 200 bytes are shown]" in text
    assert text.splitlines()[1] == "0" * 50


@posix
def test_the_environment_is_minimal_and_env_adds_to_it(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SKYE_SECRET", "hidden")
    monkeypatch.setenv("LANG", "C")
    text = ShellToolkit(allow=["env"], env={"EXTRA": "1"}).run_command.execute(command="env")
    names = {line.split("=")[0] for line in text.splitlines()[1:]}
    assert "SKYE_SECRET" not in names and "EXTRA" in names
    assert names <= {"PATH", "LANG", "LC_ALL", "HOME", "EXTRA", "PWD", "SHLVL", "_", "OLDPWD"}


@posix
def test_the_program_runs_in_cwd(tmp_path: Path):
    text = ShellToolkit(allow=["pwd"], cwd=tmp_path).run_command.execute(command="pwd")
    assert text == f"exit code 0\n{tmp_path.resolve()}\n"


@posix
@pytest.mark.asyncio
async def test_a_refused_command_is_an_error_message_and_not_an_exception():
    toolkit = ShellToolkit(allow=["echo"])
    message = await toolkit.run(
        CapabilityCall(id="1", name="shell.run_command", arguments={"command": "rm x"})
    )
    assert message.status == CapabilityStatus.ERROR
    ok = await toolkit.run(
        CapabilityCall(id="2", name="shell.run_command", arguments={"command": "echo hi"})
    )
    assert ok.status == CapabilityStatus.OK and "hi" in ok.content


def test_the_door_registers_the_toolkit_by_text():
    registrar = Registrar()
    shell.register(registrar)
    assert registrar._tables["toolkit"]["shell"].target == "skye.tools.plugins.shell:ShellToolkit"
    assert registrar.get("toolkit", "shell") is ShellToolkit


def test_importing_the_door_does_not_import_the_class():
    code = (
        "import sys\n"
        "import skye.tools\n"
        "import skye.tools.plugins.shell as door\n"
        "assert 'skye.tools.plugins.shell.toolkit' not in sys.modules\n"
        "door.ShellToolkit\n"
        "assert 'skye.tools.plugins.shell.toolkit' in sys.modules\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
