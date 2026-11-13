"""Build hook of the wheel: no comment is shipped (task 24.3) and the templates are one archive
(task 24.7).

The repository and the sdist keep every comment. The wheel gets a copy of each Python file and of
each bundled ``.skye`` template with the comments removed. The hook never writes to the source: it
works in a temporary folder and hands the copies to hatchling as forced files, which replace the
files of the same path.

* Python files: the COMMENT tokens of the standard library ``tokenize`` are cut. Every line break
  stays, so the line numbers of a traceback are the ones of the source. A shebang and a coding line
  (the first two lines) stay. A string, an f-string and a docstring are never touched. The result
  must compile and have the same AST as the source, else the file is shipped as it is.
* ``.skye`` files: the ``#`` and ``/* ... */`` comments of the body are cut with the lexer of the
  language. The front matter stays byte for byte. The result must give the same tokens as the
  source, else the file is shipped as it is.

* Templates (task 24.7): the stripped ``.skye`` templates are not shipped as loose files. They go
  into ONE archive,
  ``skye/prompts/templates.zip`` (``zipfile``, deflate level 9, entries sorted by name, a fixed date
  and fixed
  permissions, so two builds give the same bytes). The loader reads the archive by name in an
  installed wheel and
  the folder in a source checkout. ``pyproject.toml`` leaves the loose files out of the wheel.

The hook does nothing for an editable install and for the sdist, so the tree of a developer is
never changed.

Raises: nothing; a file that is not as expected is kept as it is, with a warning on stderr.
Missing: the standard library only; ``hatchling`` is imported when it is there (the tests import
    this module without it).
Concurrency: one build at a time; the temporary folder belongs to one hook object.
"""

from __future__ import annotations

import ast
import atexit
import io
import re
import shutil
import sys
import tempfile
import tokenize
import zipfile
from pathlib import Path

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # the tests import this module without hatchling

    class BuildHookInterface:  # type: ignore[no-redef]
        """Stands in for the hatchling class when hatchling is not installed."""


FENCE = "---"
TEMPLATES_PREFIX = "skye/prompts/templates/"
ARCHIVE_WHEEL_PATH = "skye/prompts/templates.zip"
_ARCHIVE_DATE = (
    1980,
    1,
    1,
    0,
    0,
    0,
)  # the earliest date a zip can hold: the same bytes in every build
_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def _warn(path: str, why: str) -> None:
    print(f"hatch_build: {path}: {why}; the file keeps its comments", file=sys.stderr)


def strip_python(source: str, name: str = "<source>") -> str:
    """The Python ``source`` without its comments, with the same line breaks and the same AST.

    A shebang and a coding line (the first two lines) stay. If the text cannot be tokenized, or
    the stripped text does not compile or does not give the same AST, the source is returned
    unchanged.
    """
    lines = list(io.StringIO(source, newline=""))
    try:
        comments = [
            token.start
            for token in tokenize.generate_tokens(io.StringIO(source, newline="").readline)
            if token.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, SyntaxError) as error:
        _warn(name, f"cannot be tokenized ({error})")
        return source
    for row, column in comments:
        line = lines[row - 1]
        if row == 1 and line.startswith("#!"):
            continue
        if row <= 2 and _CODING.match(line):
            continue
        code = line[:column].rstrip(" \t\f")
        ending = line[len(line.rstrip("\r\n")) :]
        lines[row - 1] = code + ending
    result = "".join(lines)
    try:
        same = ast.dump(ast.parse(result)) == ast.dump(ast.parse(source))
    except SyntaxError:
        same = False
    if not same:
        _warn(name, "the stripped text does not give the same AST")
        return source
    return result


def _front_matter_length(text: str) -> int:
    """The length of the front matter of a ``.skye`` text, fences and line breaks included."""
    lines = text.split("\n")
    if lines[0].lstrip("\ufeff").rstrip("\r ") != FENCE:
        return 0
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r ") == FENCE), None)
    if close is None:
        return 0
    return sum(len(line) + 1 for line in lines[: close + 1])


def _lexer(root: Path):
    """The function ``tokenize`` of the lexer of the language, read from the sources in ``root``."""
    sys.path.insert(0, str(root))
    try:
        from skye.base.dsl.lexer import tokenize as lexer_tokenize

        return lexer_tokenize
    finally:
        sys.path.remove(str(root))


def forget_skye(before: set[str]) -> None:
    """Drop the ``skye`` modules that were imported after ``before`` was taken.

    In a build the project is not imported yet, so the lexer and its imports are dropped and the
    build process keeps no copy of the project. Where it is already imported (a test), nothing goes.
    """
    for name in [
        m for m in sys.modules if m not in before and (m == "skye" or m.startswith("skye."))
    ]:
        del sys.modules[name]


def _signature(tokens) -> list[tuple]:
    """What makes two token streams the same text for the language: kind, text and value.

    A run of newline tokens counts as one and a newline before the first token as none: a blank
    line, or the line of a block comment that spanned lines, ends nothing.
    """
    out: list[tuple] = []
    for token in tokens:
        if token.kind == "newline" and (not out or out[-1][0] == "newline"):
            continue
        out.append((token.kind, token.text, token.value))
    return out


def _strip_gap(gap: str) -> str:
    """A gap between two tokens, each comment turned into a NUL (a gap holds blanks, comments)."""
    out: list[str] = []
    i = 0
    while i < len(gap):
        char = gap[i]
        if char in " \t\r":
            out.append(char)
            i += 1
        elif char == "#":
            out.append("\0")
            i = len(gap)
        elif gap.startswith("/*", i):
            close = gap.find("*/", i + 2)
            if close == -1:
                raise ValueError("unterminated block comment")
            out.append("\0" + "\n" * gap.count("\n", i, close))  # the line numbers stay
            i = close + 2
        else:
            raise ValueError(f"unexpected {char!r} in a gap between two tokens")
    return "".join(out)


def _tidy(text: str) -> str:
    """Turn each NUL into a blank, cut the trailing blanks of those lines, drop no line."""
    out: list[str] = []
    for line in text.split("\n"):
        if "\0" not in line:
            out.append(line)
            continue
        cr = "\r" if line.endswith("\r") else ""
        core = line[: len(line) - len(cr)].replace("\0", " ").rstrip(" \t")
        out.append((core if core.strip() else "") + cr)
    return "\n".join(out)


def strip_skye(text: str, tokenize_skye, name: str = "<template>") -> str:
    """The ``.skye`` ``text`` without the ``#`` and ``/* ... */`` comments of its body.

    The front matter stays byte for byte. ``tokenize_skye`` is the lexer. Every line break stays,
    so the line numbers that a built template keeps are the ones of the source; a comment alone on
    a line leaves an empty line, and a comment after code leaves the code with no trailing blanks.
    The tokens of the result must equal those of the source (kind, text and value), else the text
    is returned unchanged.
    """
    head_length = _front_matter_length(text)
    head, body = text[:head_length], text[head_length:]
    tokens, errors = tokenize_skye(body, name)
    if errors:
        _warn(name, "the lexer reports mistakes")
        return text
    pieces: list[str] = []
    position = 0
    for token in tokens:
        pieces.append(_strip_gap(body[position : token.start]))
        pieces.append(body[token.start : token.end])
        position = token.end
    pieces.append(_strip_gap(body[position:]))
    joined = "".join(pieces)
    if "\0" not in joined:
        return text
    new_body = _tidy(joined)
    again, new_errors = tokenize_skye(new_body, name)
    if new_errors or _signature(again) != _signature(tokens):
        _warn(name, "the stripped text does not give the same tokens")
        return text
    return head + new_body


def make_copies(source_root: Path, target: Path) -> dict[str, str]:
    """Write the stripped copies of the ``.py`` and ``.skye`` files of ``source_root``.

    Returns:
        A mapping from the absolute path of each copy to its path in the wheel (``skye/...``).
    """
    before = set(sys.modules)
    tokenize_skye = _lexer(source_root.parent)
    forced: dict[str, str] = {}
    try:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(source_root.parent)
            if path.suffix == ".py":
                original = path.read_text(encoding="utf-8")
                stripped = strip_python(original, str(relative))
            elif path.suffix == ".skye":
                original = path.read_text(encoding="utf-8")
                try:
                    stripped = strip_skye(original, tokenize_skye, str(relative))
                except ValueError as error:
                    _warn(str(relative), str(error))
                    continue
            else:
                continue
            if stripped == original:
                continue
            copy = target / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(stripped.encode("utf-8"))
            forced[str(copy)] = relative.as_posix()
    finally:
        forget_skye(before)
    return forced


def pack_templates(templates: dict[str, bytes]) -> bytes:
    """The bytes of one zip archive that holds ``templates`` (a name such as ``chat.skye`` to its
    bytes).

    The entries are sorted by name, deflated at level 9, with a fixed date, a fixed system and fixed
    permissions, so the
    same templates always give the same bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(templates):
            info = zipfile.ZipInfo(name, date_time=_ARCHIVE_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(
                info, templates[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return buffer.getvalue()


def collect_templates(source_root: Path, copies: dict[str, str]) -> dict[str, bytes]:
    """The bundled templates, each one stripped when ``make_copies`` made a copy of it, else as it
    is in the source.

    Returns:
        A mapping from a path inside the templates folder (``chat.skye``, ``common/x.skye``) to its
        bytes, sorted by name.
    """
    by_destination = {destination: copy for copy, destination in copies.items()}
    found: dict[str, bytes] = {}
    templates = source_root / "prompts" / "templates"
    for path in sorted(templates.rglob("*.skye")):
        destination = path.relative_to(source_root.parent).as_posix()
        copy = by_destination.get(destination)
        found[path.relative_to(templates).as_posix()] = (
            Path(copy).read_bytes() if copy else path.read_bytes()
        )
    return found


def make_wheel_files(source_root: Path, target: Path) -> dict[str, str]:
    """The files that the wheel gets in place of the source: stripped Python files and the archive
    of the templates.

    Returns:
        A mapping from the absolute path of each file to its path in the wheel (``skye/...``). The
        loose ``.skye`` templates
        are not in it: they are in the archive.
    """
    copies = make_copies(source_root, target)
    templates = collect_templates(source_root, copies)
    for copy in [
        c for c, destination in copies.items() if destination.startswith(TEMPLATES_PREFIX)
    ]:
        del copies[copy]
    if templates:
        archive = target / ARCHIVE_WHEEL_PATH
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(pack_templates(templates))
        copies[str(archive)] = ARCHIVE_WHEEL_PATH
    return copies


class CustomBuildHook(BuildHookInterface):
    """Gives the wheel stripped Python files and one archive of the templates; no-op otherwise."""

    PLUGIN_NAME = "custom"
    _folder: str | None = None

    def applies(self, version: str) -> bool:
        """Whether this build is a real wheel: the wheel target, and not the editable version."""
        return self.target_name == "wheel" and version != "editable"

    def initialize(self, version: str, build_data: dict) -> None:
        if not self.applies(version):
            return
        self._folder = tempfile.mkdtemp(prefix="skye-build-")
        atexit.register(shutil.rmtree, self._folder, ignore_errors=True)
        copies = make_wheel_files(Path(self.root) / "src" / "skye", Path(self._folder))
        build_data["force_include"].update(copies)

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        if self._folder:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None
