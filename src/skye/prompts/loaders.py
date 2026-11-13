# task 7.3, D60, D76
"""Template loaders for Skye prompts (structure).

Discovers template files in the `templates/` directory and registers them on a
prompt builder (liteprompt-style loaders and registry; rendering uses the stdlib engine in
`skye.prompts.engine`, not Jinja2, interpolation only). `*.skye` prompt files are read next
to `*.jinja`, `*.txt`, `*.template` and `*.tmpl` text templates (`{{ }}` and filters; a `{% %}`
tag makes the file fail to load); when a `.skye` file and another file share a name, only
the `.skye` one is registered.
"""

from __future__ import annotations

import logging
import posixpath
import threading
import zipfile
from pathlib import Path
from typing import Any

from skye.base.dsl.include import Resolved
from skye.base.dsl.include import INCLUDE_LINE
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
# every `.skye` entry by its path in the archive (the partials too)
_archive_members: dict[str, str] = {}


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
    global _archive_index, _archive_members
    with _archive_lock:
        try:
            status = TEMPLATES_ARCHIVE.stat()
            stamp = (status.st_size, status.st_mtime_ns)
            if _archive_index is not None and _archive_index[0] == stamp:
                return _archive_index
            with zipfile.ZipFile(TEMPLATES_ARCHIVE) as archive:
                members = {
                    info.filename: archive.read(info).decode("utf-8")
                    for info in archive.infolist()
                    if info.filename.endswith(".skye")
                }
                texts = {Path(n).stem: t for n, t in members.items() if "/" not in n}
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
        _archive_members = members
        return _archive_index


def bundled_names() -> list[str]:
    """The names of the bundled ``.skye`` templates, sorted: the files of a source checkout, else the entries of the archive."""
    if _folder_has_templates():
        return sorted(path.stem for path in TEMPLATES_DIR.glob("*.skye"))
    if TEMPLATES_ARCHIVE.is_file():
        return sorted(_archive()[1])
    return []


def bundled_partials() -> list[str]:
    """The paths of the shared ``.skye`` files that bundled templates include (``common/x.skye``), sorted."""
    if _folder_has_templates():
        return sorted(
            path.relative_to(TEMPLATES_DIR).as_posix()
            for path in TEMPLATES_DIR.rglob("*.skye")
            if path.parent != TEMPLATES_DIR
        )
    if TEMPLATES_ARCHIVE.is_file():
        _archive()
        return sorted(name for name in _archive_members if "/" in name)
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


# task 25.4, Requirement 63
class CatalogueResolver:
    """The resolver of the ``include`` lines of a bundled template.

    A target is a path relative to the including file, inside the catalogue: the folder of a source checkout or the
    entries of ``templates.zip``. A path above the catalogue is refused. The partials are in a subfolder, so they are
    not templates, and a file of the user has no way to name them (its resolver reads only its own folder).
    """

    def __call__(self, target: str, from_key: str | None) -> Resolved:
        """The text of ``target`` (``Resolved.key`` is its path in the catalogue).

        Raises:
            ValueError: The path leaves the catalogue.
            FileNotFoundError: There is no such file in the catalogue.
        """
        path = posixpath.normpath(posixpath.join(posixpath.dirname(from_key or ""), target))
        if path == ".." or path.startswith(("../", "/")):
            raise ValueError("it is outside the bundled templates")
        if _folder_has_templates():
            file = (TEMPLATES_DIR / path).resolve()
            if not file.is_relative_to(TEMPLATES_DIR.resolve()) or not file.is_file():
                raise FileNotFoundError(f"no such file in {TEMPLATES_DIR}")
            return Resolved(text=file.read_text(encoding="utf-8"), name=path, key=path)
        _archive()
        if path not in _archive_members:
            raise FileNotFoundError(f"no such file in {TEMPLATES_ARCHIVE}")
        return Resolved(text=_archive_members[path], name=path, key=path)

    def fingerprint(self) -> tuple[Any, ...]:
        """What changes when a file of the catalogue changes: the stat of each file, or the stamp of the archive."""
        if _folder_has_templates():
            return tuple(
                (p.name, s.st_size, s.st_mtime_ns)
                for p in sorted(TEMPLATES_DIR.rglob("*.skye"))
                for s in (p.stat(),)
            )
        return _archive()[0] if TEMPLATES_ARCHIVE.is_file() else ()


catalogue_resolver = CatalogueResolver()


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
    compiles it at its first use, and a mistake in it shows then. A `.skye` file of a folder given by the caller that
    ``include``s another file is registered now, with the file resolver of its folder; a file whose front matter says
    ``partial = true`` is a part of other templates and is not registered.

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
    own_folder = directory is not None and directory.resolve() != TEMPLATES_DIR.resolve()
    loaded = 0
    for name, path in files.items():
        try:
            if register_bundled is not None and path.suffix == ".skye":
                text = path.read_text(encoding="utf-8")
                version, partial = _front(text, path)
                if partial:
                    continue
                if own_folder and INCLUDE_LINE.search(text):
                    builder.register_template(name, str(path), version=version or "1.0", from_string=False)
                else:
                    register_bundled(name, text, path, version or "1.0")
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


def _front(text: str, path: Path) -> tuple[str | None, bool]:
    """The ``version`` in the front matter of the text of a ``.skye`` file, and whether it says ``partial = true``."""
    metadata, _, errors = split_metadata(text, str(path))
    version = metadata.get("version")
    return (str(version) if version is not None and not errors else None), metadata.get("partial") is True


def _version_in(text: str, path: Path) -> str | None:
    """The ``version`` in the front matter of the text of a ``.skye`` file, or ``None``."""
    return _front(text, path)[0]
