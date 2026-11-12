"""``FilesToolkit``: the built-in toolkit ``files``, two read-only tools for the files under one folder (Requirement 62.7, D111).

The folder is the option ``root``, and it is required. The tools are ``files.list_files`` and ``files.read_file``. They only read:
there is no write, no delete, no execute and no network. Every path the model gives is joined to ``root`` and resolved, and it must stay
inside ``root`` after the links are resolved. An absolute path, a drive path, a NUL character, a ``..`` that leaves ``root`` and a link
that points outside are refused with a plain error that does not name the real path. Hidden entries (a name that starts with a dot) are
left out of a listing and refused by ``read_file``, unless ``include_hidden`` is set.

Example:
    >>> import asyncio, tempfile, pathlib
    >>> folder = pathlib.Path(tempfile.mkdtemp())
    >>> _ = (folder / "notes.txt").write_text("hello")
    >>> toolkit = FilesToolkit(root=folder)
    >>> [schema.name for schema in asyncio.run(toolkit.list_schemas())]
    ['files.list_files', 'files.read_file']
    >>> toolkit.list_files.execute()
    ['notes.txt']
    >>> toolkit.read_file.execute(path="notes.txt")
    'hello'

Raises: ``ValidationError`` at construction when ``root`` is missing or is not a folder, or ``max_bytes`` is not a positive number; a tool
    raises ``CapabilityError`` for a refused path, a missing file, a folder given to ``read_file``, a file given to ``list_files`` and a file
    that is not UTF-8 text, and ``run`` turns it into a message whose status is ``error``.
Missing: a hidden entry, an entry of a long listing past the limit and the bytes of a long file past ``max_bytes`` are not returned, and
    the result says so.
Concurrency: the toolkit holds only its settings and reads the file system on each call, so several tasks may call it at once.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from skye.base.exceptions import CapabilityError, ValidationError
from skye.tools.decorator import capability
from skye.tools.toolkit import Toolkit

#: The most entries one listing returns.
MAX_ENTRIES = 500
#: The part of a file that is looked at for a NUL byte, to tell text from binary.
_SNIFF_BYTES = 8192


class FilesToolkit(Toolkit):
    """Read the files under one folder: ``files.list_files`` and ``files.read_file``.

    Args:
        root: The folder the tools may read. Nothing outside it can be read. Required.
        max_bytes: The most bytes ``read_file`` returns for one file.
        include_hidden: Whether a name that starts with a dot is listed and read.
    """

    def __init__(
        self,
        *,
        root: str | os.PathLike[str] | None = None,
        max_bytes: int = 65536,
        include_hidden: bool = False,
    ) -> None:
        if root is None or str(root) == "":
            raise ValidationError(
                "the toolkit 'files' needs the option root, the folder it may read",
                field="root",
                value=None,
            )
        folder = Path(root).resolve()
        if not folder.is_dir():
            raise ValidationError(
                f"the option root of the toolkit 'files' is not a folder: {str(root)!r}",
                field="root",
                value=str(root),
            )
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValidationError(
                "the option max_bytes of the toolkit 'files' must be a positive number",
                field="max_bytes",
                value=max_bytes,
            )
        self._root = folder
        self._max_bytes = max_bytes
        self._include_hidden = include_hidden

    def _resolve(self, path: str) -> Path:
        """The real path of ``path`` under the root, or an error: the one place that keeps the tools inside the root."""
        if not isinstance(path, str):
            raise CapabilityError("the path must be text")
        if "\x00" in path:
            raise CapabilityError("the path has a NUL character")
        if path.startswith(("/", "\\")) or PureWindowsPath(path).drive or Path(path).is_absolute():
            raise CapabilityError(
                f"'{path}' is an absolute path; give a path inside the folder, such as 'notes.txt'"
            )
        resolved = (self._root / path).resolve()
        if not resolved.is_relative_to(self._root):
            raise CapabilityError(f"'{path}' is outside the folder that this toolkit may read")
        if not self._include_hidden and any(
            part.startswith(".") for part in resolved.relative_to(self._root).parts
        ):
            raise CapabilityError(
                f"'{path}' is a hidden file or folder, which this toolkit does not read"
            )
        return resolved

    @capability
    def list_files(self, path: str = ".") -> list[str]:
        """List the files and folders in a folder. A folder name ends with a slash.

        Args:
            path: The folder, relative to the root. The default is the root itself.
        """
        folder = self._resolve(path)
        if not folder.exists():
            raise CapabilityError(f"'{path}' does not exist")
        if not folder.is_dir():
            raise CapabilityError(f"'{path}' is a file, not a folder; use read_file")
        names = []
        for entry in folder.iterdir():
            if not self._include_hidden and entry.name.startswith("."):
                continue
            names.append(entry.name + "/" if entry.is_dir() else entry.name)
        names.sort()
        if len(names) > MAX_ENTRIES:
            more = len(names) - MAX_ENTRIES
            return [*names[:MAX_ENTRIES], f"[{more} more entries not shown]"]
        return names

    @capability
    def read_file(self, path: str) -> str:
        """Read a text file (UTF-8). A long file is cut and the result says so.

        Args:
            path: The file, relative to the root.
        """
        target = self._resolve(path)
        if not target.exists():
            raise CapabilityError(f"'{path}' does not exist")
        if target.is_dir():
            raise CapabilityError(f"'{path}' is a folder, not a file; use list_files")
        if not target.is_file():
            raise CapabilityError(f"'{path}' is not a regular file")
        size = target.stat().st_size
        with open(target, "rb") as handle:
            data = handle.read(self._max_bytes + 1)
        cut = len(data) > self._max_bytes
        data = data[: self._max_bytes]
        if b"\x00" in data[:_SNIFF_BYTES]:
            raise CapabilityError(f"'{path}' is not a text file")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            # A cut can end inside one character: that is not an error, the rest of the bytes still decode.
            if not cut or error.start < len(data) - 3:
                raise CapabilityError(f"'{path}' is not a UTF-8 text file") from None
            text = data[: error.start].decode("utf-8")
        if cut:
            text += f"\n[cut: the first {len(data)} of {size} bytes are shown]"
        return text
