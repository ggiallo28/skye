# D111
"""``ShellToolkit``: the built-in toolkit ``shell``, one tool that runs a program from a list of
allowed names.

It is opt-in and safe by default: ``allow`` is required. The command is split with ``shlex`` and run
WITHOUT a shell, so ``|``, ``>``, ``;`` and
``$(...)`` are plain arguments. The first word must be one of ``allow`` exactly. The environment is
minimal (``PATH``, ``LANG``, ``LC_ALL``,
``HOME`` and what ``env`` adds). A time limit kills the process, and its group on POSIX. This
toolkit is NOT a sandbox: an allowed program such
as ``git`` or ``python`` can do anything its user can do. Allow only programs that you would run
yourself.

Example:
    >>> toolkit = ShellToolkit(allow=["echo"])
    >>> toolkit.run_command.execute(command="echo hello")
    'exit code 0\\nhello\\n'

Raises: ``ValidationError`` at construction for a bad option; the tool raises ``CapabilityError``
for an empty command, a program that is not
    allowed or not found, a timeout and a command that cannot be split.
Missing: output past ``max_bytes`` is not returned, and the result says so.
Concurrency: the toolkit holds only its settings; each call starts its own process.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from skye.base.exceptions import CapabilityError, ValidationError
from skye.tools.decorator import capability
from skye.tools.toolkit import Toolkit

_KEPT = ("PATH", "LANG", "LC_ALL", "HOME")


class ShellToolkit(Toolkit):
    """Run one allowed program: ``shell.run_command``.

    Args:
        allow: The names of the programs the tool may run, such as ``["git", "ls"]``. A name has no
            path. Required.
        cwd: The folder the program runs in. The default is the current folder.
        timeout: Seconds before the process is killed.
        max_bytes: The most bytes of output returned.
        env: Extra environment variables for the program.
    """

    def __init__(
        self,
        *,
        allow: Sequence[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float = 30.0,
        max_bytes: int = 65536,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not allow or isinstance(allow, str):
            raise ValidationError(
                "the toolkit 'shell' needs the option allow, a list of program names",
                field="allow",
                value=allow,
            )
        for name in allow:
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise ValidationError(
                    f"a name in allow must be a program name with no path: {name!r}",
                    field="allow",
                    value=name,
                )
        folder = Path(cwd if cwd is not None else os.getcwd()).resolve()
        if not folder.is_dir():
            raise ValidationError(
                f"the option cwd is not a folder: {str(cwd)!r}", field="cwd", value=str(cwd)
            )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValidationError(
                "the option timeout must be a positive number", field="timeout", value=timeout
            )
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValidationError(
                "the option max_bytes must be a positive number", field="max_bytes", value=max_bytes
            )
        self._allow = tuple(allow)
        self._cwd = folder
        self._timeout = float(timeout)
        self._max_bytes = max_bytes
        self._env = dict(env or {})

    def _environment(self) -> dict[str, str]:
        base = {key: os.environ[key] for key in _KEPT if key in os.environ}
        return {**base, **self._env}

    @capability
    def run_command(self, command: str) -> str:
        """Run a program with arguments, for example ``git status``. Returns the exit code and the
        output.

        Args:
            command: The program and its arguments. There is no shell: a pipe or a redirect is not
                understood.
        """
        try:
            args = shlex.split(command)
        except ValueError as error:
            raise CapabilityError(f"the command cannot be split: {error}") from None
        if not args:
            raise CapabilityError(
                f"the command is empty; the allowed programs are: {', '.join(self._allow)}"
            )
        if args[0] not in self._allow:
            raise CapabilityError(
                f"'{args[0]}' is not allowed; the allowed programs are: {', '.join(self._allow)}"
            )
        environment = self._environment()
        program = shutil.which(args[0], path=environment.get("PATH"))
        if program is None:
            raise CapabilityError(f"the program '{args[0]}' was not found")
        process = subprocess.Popen(  # noqa: S603 - no shell, the first word is in the allow list
            [program, *args[1:]],
            cwd=self._cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        try:
            out, err = process.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise CapabilityError(
                f"'{args[0]}' did not finish in {self._timeout:g} seconds"
            ) from None
        text = out.decode("utf-8", "replace")
        if err:
            text += "--- stderr ---\n" + err.decode("utf-8", "replace")
        data = text.encode("utf-8")
        if len(data) > self._max_bytes:
            text = data[: self._max_bytes].decode("utf-8", "ignore")
            text += f"\n[cut: the first {self._max_bytes} of {len(data)} bytes are shown]"
        return f"exit code {process.returncode}\n{text}"
