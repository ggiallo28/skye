"""Template loaders for Skye prompts (structure task 7.3).

Discovers template files in the `templates/` directory and registers them on a
prompt builder (liteprompt-style loaders and registry; rendering uses the stdlib engine in
`skye.prompts.engine`, not Jinja2, interpolation only). `*.skye` prompt files (D60) are read next
to `*.jinja`, `*.txt`, `*.template` and `*.tmpl` text templates (`{{ }}` and filters; a `{% %}`
tag makes the file fail to load, D76); when a `.skye` file and another file share a name, only
the `.skye` one is registered.
"""

from __future__ import annotations

import logging
import threading
import zipfile
from pathlib import Path
from typing import Any

from skye.base.dsl.metadata import split_metadata
from skye.base.exceptions import ValidationError

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

#: The archive that holds the bundled templates in an installed wheel (made at build by ``hatch_build.py``, task 24.7); a
#: source checkout keeps the loose files in ``TEMPLATES_DIR`` and has no archive.
TEMPLATES_ARCHIVE = Path(__file__).parent / "templates.zip"

#: Extensions read, in order of preference: a `.skye` file wins over a template of the same name.
TEMPLATE_EXTENSIONS: tuple[str, ...] = (".skye", ".jinja", ".txt", ".template", ".tmpl")


def discover_templates(directory: Path) -> dict[str, Path]:
    """Find the template files of ``directory``, one per name (the file stem).

    Args:
        directory: The folder to read.

    Returns:
        The file of each template name; a `.skye` file wins over the other extensions.
    """
    found: dict[str, Path] = {}
    for extension in TEMPLATE_EXTENSIONS:
        for path in sorted(directory.glob(f"*{extension}")):
            found.setdefault(path.stem, path)
    return found


_archive_lock = threading.Lock()
_archive_index: tuple[tuple[int, int], dict[str, tuple[str, str]]] | None = None


def _folder_has_templates() -> bool:
    """Whether the folder of a source checkout holds the bundled templates."""
    return TEMPLATES_DIR.is_dir() and any(TEMPLATES_DIR.glob("*.skye"))


def _archive() -> tuple[tuple[int, int], dict[str, tuple[str, str]]]:
    """The bundled templates of the archive: the stamp of the archive and ``{name: (text, version)}``.

    The archive is opened once for the process, the first time it is needed (never at ``import skye``): every entry is read in
    one pass, so a later builder or a later use reads nothing. The lock makes two threads read it once.

    Raises:
        ValidationError: The archive cannot be read, or an entry is not UTF-8 text.
    """
    global _archive_index
    with _archive_lock:
        try:
            status = TEMPLATES_ARCHIVE.stat()
            stamp = (status.st_size, status.st_mtime_ns)
            if _archive_index is not None and _archive_index[0] == stamp:
                return _archive_index
            with zipfile.ZipFile(TEMPLATES_ARCHIVE) as archive:
                texts = {
                    Path(info.filename).stem: archive.read(info).decode("utf-8")
                    for info in archive.infolist()
                    if info.filename.endswith(".skye")
                }
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as error:
            raise ValidationError(
                f"The archive of the bundled templates cannot be read: {TEMPLATES_ARCHIVE} ({error})",
                field="templates",
                value=str(TEMPLATES_ARCHIVE),
            ) from error
        index = {
            name: (text, _version_in(text, Path(f"{TEMPLATES_ARCHIVE}/{name}.skye")) or "1.0")
            for name, text in texts.items()
        }
        _archive_index = (stamp, index)
        return _archive_index


def bundled_names() -> list[str]:
    """The names of the bundled ``.skye`` templates, sorted: the files of a source checkout, else the entries of the archive."""
    if _folder_has_templates():
        return sorted(path.stem for path in TEMPLATES_DIR.glob("*.skye"))
    if TEMPLATES_ARCHIVE.is_file():
        return sorted(_archive()[1])
    return []


def bundled_origin(name: str) -> str:
    """Where a bundled template is, as the text that diagnostics name: its file, or ``templates.zip/<name>.skye``."""
    if _folder_has_templates():
        return str(TEMPLATES_DIR / f"{name}.skye")
    return f"{TEMPLATES_ARCHIVE}/{name}.skye"


def read_bundled(name: str) -> str:
    """The text of a bundled ``.skye`` template, from the folder of a source checkout or from the archive.

    Raises:
        FileNotFoundError: There is no bundled template of that name (the message names it and where it was looked for).
        ValidationError: The archive cannot be read.
    """
    if _folder_has_templates():
        path = TEMPLATES_DIR / f"{name}.skye"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"The bundled template {name!r} is not in {TEMPLATES_DIR}"
            ) from None
    if not TEMPLATES_ARCHIVE.is_file():
        raise FileNotFoundError(
            f"The bundled template {name!r} was not found: there is no {TEMPLATES_ARCHIVE}"
        )
    entry = _archive()[1].get(name)
    if entry is None:
        raise FileNotFoundError(f"The bundled template {name!r} is not in {TEMPLATES_ARCHIVE}")
    return entry[0]


def _load_from_archive(builder: Any) -> int:
    """Register the bundled templates of the archive; each is compiled at its first use, as a file of the folder is."""
    stamp, index = _archive()
    register_bundled = getattr(builder, "register_bundled_template", None)
    loaded = 0
    for name in sorted(index):
        text, version = index[name]
        origin = Path(f"{TEMPLATES_ARCHIVE}/{name}.skye")
        if register_bundled is not None:
            register_bundled(name, text, origin, version, stamp=(len(text), stamp[1]))
        else:
            builder.register_template(name, text, version=version, from_string=True)
        loaded += 1
    logger.debug(
        "Loaded prompt templates", extra={"count": loaded, "directory": str(TEMPLATES_ARCHIVE)}
    )
    return loaded


def load_default_templates(builder: Any, directory: Path | None = None) -> int:
    """Register the templates of the templates folder.

    A ``.skye`` file is registered under the ``version`` of its front matter (``---`` ... ``---``);
    any other file, or one without a version, as ``1.0``.

    A file that cannot be read is skipped with a warning in the log. A bundled `.skye` file is not compiled here: the builder
    compiles it at its first use, and a mistake in it shows then.

    Args:
        builder: The prompt builder (anything with ``register_template``).
        directory: The folder to read (default: the bundled templates: the folder of a source checkout, else the archive of an
            installed wheel).

    Returns:
        How many templates were registered.
    """
    if directory is None and not _folder_has_templates() and TEMPLATES_ARCHIVE.is_file():
        return _load_from_archive(builder)
    templates_dir = directory or TEMPLATES_DIR
    if not templates_dir.exists():
        logger.warning("Templates directory not found", extra={"directory": str(templates_dir)})
        return 0

    files = discover_templates(templates_dir)
    if not files:
        logger.warning("No template files found", extra={"directory": str(templates_dir)})
        return 0

    # A `.skye` file is only read here (its text and its version); the builder compiles it at its first use.
    register_bundled = getattr(builder, "register_bundled_template", None)
    loaded = 0
    for name, path in files.items():
        try:
            if register_bundled is not None and path.suffix == ".skye":
                text = path.read_text(encoding="utf-8")
                register_bundled(name, text, path, _version_in(text, path) or "1.0")
            else:
                version = _metadata_version(path) or "1.0"
                builder.register_template(name, str(path), version=version, from_string=False)
        except (OSError, ValueError) as e:
            logger.warning(
                "Could not load template",
                extra={"template": name, "path": str(path), "error": str(e)},
            )
            continue
        loaded += 1

    logger.debug(
        "Loaded prompt templates", extra={"count": loaded, "directory": str(templates_dir)}
    )
    return loaded


def _metadata_version(path: Path) -> str | None:
    """The ``version`` in the front matter of a ``.skye`` file, or ``None``."""
    if path.suffix != ".skye":
        return None
    return _version_in(path.read_text(encoding="utf-8"), path)


def _version_in(text: str, path: Path) -> str | None:
    """The ``version`` in the front matter of the text of a ``.skye`` file, or ``None``."""
    metadata, _, errors = split_metadata(text, str(path))
    version = metadata.get("version")
    return str(version) if version is not None and not errors else None
