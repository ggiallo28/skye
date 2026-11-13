# Requirement 62.8
"""The seam for the skills: a ``SKILL.md`` given to an agent adds the toolkit ``files`` for its
folder.

The agent asks the registrar for the toolkit ``files`` and builds it once, limited to the folder of
each skill, so it can read what
the skills ship (``references/``, scripts) and nothing else. This module never imports
``skye.tools``: the class is resolved by the
registrar, from the text a plugin registered, only when a skill is given. The skill itself and the
agent loop are the agents spec.

Raises: ``ConfigurationError`` when a path is not a ``SKILL.md`` (or a folder that holds one), or
when no toolkit ``files`` is registered.
Missing: not applicable.
Concurrency: reads the registrar and the file system; holds no state.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar

#: The name of the file that makes a folder a skill.
SKILL_FILE = "SKILL.md"
#: The toolkit that reads the files of a skill.
FILES_TOOLKIT = "files"


def skill_folder(skill: str | Path) -> Path:
    """The folder of a skill: the parent of its ``SKILL.md``, or the folder itself when it holds
    one.

    Raises:
        ConfigurationError: The path is neither a ``SKILL.md`` nor a folder that holds one.
    """
    path = Path(skill)
    if path.is_dir() and (path / SKILL_FILE).is_file():
        return path.resolve()
    if path.name == SKILL_FILE and path.is_file():
        return path.resolve().parent
    raise ConfigurationError(
        f"a skill is a {SKILL_FILE} or a folder that holds one, got {str(skill)!r}",
        details={"skill": str(skill)},
    )


def skill_toolkits(
    skills: Iterable[str | Path], *, registrar: Registrar | None = None
) -> list[Any]:
    """The ``files`` toolkit for the skills: one instance, limited to the folders of those skills.

    The toolkit always gets ``roots``, even for one skill, so there are two tools in all and each
    path starts with the name of a skill folder,
    whatever the number of skills. A folder that repeats is read once.

    Args:
        skills: Paths of ``SKILL.md`` files, or of folders that hold one.
        registrar: The registrar to read; the default one of the process when omitted.

    Returns:
        A list with the one toolkit; empty when no skill is given and then nothing is resolved.

    Raises:
        ConfigurationError: A path is not a skill, or no toolkit ``files`` is registered (the error
            lists the registered names).
    """
    folders = list(dict.fromkeys(skill_folder(skill) for skill in skills))
    if not folders:
        return []
    source = registrar if registrar is not None else get_registrar()
    build = source.get("toolkit", FILES_TOOLKIT)
    return [build(roots=folders)]


__all__ = ["FILES_TOOLKIT", "SKILL_FILE", "skill_folder", "skill_toolkits"]
