"""The wheel has no comment (task 24.3 of the plugins spec, O77).

`hatch_build.py` gives the wheel a copy of each Python file and of each bundled `.skye` template
with the comments removed. The repository and the sdist keep them, an editable build changes
nothing, and what the copies mean stays the same: the AST of a Python file, the line numbers, the
front matter and the objects that a template builds to.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import posixpath
import tarfile
import tokenize
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from skye.base.dsl import Resolved
from skye.dsl import build
from tests.budget import measure

ROOT = measure.ROOT
SRC = ROOT / "src" / "skye"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hatch_build", ROOT / "scripts" / "hatch_build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fingerprint() -> dict[str, str]:
    """A hash of every file the hook reads, to prove that a build never writes to the source."""
    found = {}
    for path in sorted(SRC.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".skye"}:
            found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    return _load_hook()


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """The wheel built from the tree, the sdist, and the wheel `uv build` makes from the sdist."""
    before = _fingerprint()
    direct = measure.build_wheel(tmp_path_factory.mktemp("direct"))
    after = _fingerprint()
    both = tmp_path_factory.mktemp("both")
    measure.subprocess.run(
        ["uv", "build", "--out-dir", str(both)], cwd=ROOT, check=True, capture_output=True
    )
    return {
        "wheel": direct,
        "sdist": next(both.glob("skyeai-*.tar.gz")),
        "from_sdist": next(both.glob("skyeai-*.whl")),
        "source_unchanged": before == after,
    }


def _entries(wheel: Path) -> dict[str, bytes]:
    """The files of the wheel under `skye/`; the templates of `templates.zip` appear as the `.skye`
    files they were (task 24.7)."""
    found: dict[str, bytes] = {}
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if not name.startswith("skye/"):
                continue
            data = archive.read(name)
            if name == "skye/prompts/templates.zip":
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for member in inner.namelist():
                        found[f"skye/prompts/templates/{member}"] = inner.read(member)
            else:
                found[name] = data
    return found


def _comments(source: str) -> list[tuple[int, str]]:
    return [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source, newline="").readline)
        if token.type == tokenize.COMMENT
    ]


def _is_kept(row: int, text: str) -> bool:
    return (row == 1 and text.startswith("#!")) or (row <= 2 and "coding" in text)


@pytest.mark.parametrize("which", ["wheel", "from_sdist"])
def test_no_python_file_of_the_wheel_has_a_comment(built, which) -> None:
    found = {}
    for name, data in _entries(built[which]).items():
        if name.endswith(".py"):
            left = [c for c in _comments(data.decode("utf-8")) if not _is_kept(*c)]
            if left:
                found[name] = left[:2]
    assert not found, found


def test_every_python_file_has_the_same_ast_as_its_source(built) -> None:
    different = []
    for name, data in _entries(built["wheel"]).items():
        if name.endswith(".py"):
            original = (ROOT / "src" / name).read_text(encoding="utf-8")
            if ast.dump(ast.parse(data.decode("utf-8"))) != ast.dump(ast.parse(original)):
                different.append(name)
    assert not different, different


def test_every_python_file_keeps_its_line_numbers(built) -> None:
    different = []
    for name, data in _entries(built["wheel"]).items():
        if name.endswith((".py", ".skye")):
            original = (ROOT / "src" / name).read_bytes()
            if data.count(b"\n") != original.count(b"\n"):
                different.append(name)
    assert not different, different


def _catalogue(texts: dict[str, str]):
    """The catalogue resolver over a mapping from a path in the templates folder to its text.

    The partials are in the mapping too.
    """

    def resolve(target: str, from_key: str | None) -> Resolved:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(from_key or ""), target))
        return Resolved(text=texts[path], name=path, key=path)

    return resolve


def test_every_bundled_template_builds_to_equal_objects(built) -> None:
    prefix = "skye/prompts/templates/"
    entries = {n: d for n, d in _entries(built["wheel"]).items() if n.endswith(".skye")}
    assert len(entries) >= 9  # 6 templates and the 3 shared parts
    stripped = {n[len(prefix) :]: d.decode("utf-8") for n, d in entries.items()}
    original = {n: (ROOT / "src" / prefix / n).read_text(encoding="utf-8") for n in stripped}
    with_comments, without = _catalogue(original), _catalogue(stripped)
    different = [
        n
        for n in stripped
        if build(stripped[n], resolver=without, key=n)
        != build(original[n], resolver=with_comments, key=n)
    ]
    assert not different, different


def test_the_templates_lose_their_comments_and_keep_their_front_matter(built, hook) -> None:
    entries = _entries(built["wheel"])
    lost = 0
    for name, data in entries.items():
        if not name.endswith(".skye"):
            continue
        stripped = data.decode("utf-8")
        original = (ROOT / "src" / name).read_text(encoding="utf-8")
        head = hook._front_matter_length(original)
        assert stripped[:head] == original[:head], name
        assert "/*" not in stripped[head:] or "/*" in _strings_of(stripped[head:]), name
        lost += len(original) - len(stripped)
    assert lost == 0  # the bundled templates keep no comment (task 24.11): nothing to take out


def _strings_of(text: str) -> str:
    """The text of the string tokens of a `.skye` body (a `/*` there is not a comment)."""
    from skye.base.dsl.lexer import tokenize

    tokens, _ = tokenize(text, "<test>")
    return "".join(t.text for t in tokens if t.kind == "string")


def test_the_source_tree_is_not_written_to_by_a_wheel_build(built) -> None:
    assert built["source_unchanged"]


def test_the_sdist_keeps_the_comments_and_the_hook(built) -> None:
    with tarfile.open(built["sdist"]) as archive:
        members = {m.name.split("/", 1)[1]: m for m in archive.getmembers() if "/" in m.name}
        assert "scripts/hatch_build.py" in members
        template = "src/skye/prompts/templates/extraction_generic.skye"
        assert archive.extractfile(members[template]).read() == (ROOT / template).read_bytes()
        for relative in ("src/skye/base/plugins.py", "src/skye/utils/cli.py"):
            original = (ROOT / relative).read_bytes()
            assert archive.extractfile(members[relative]).read() == original


def test_an_editable_or_sdist_build_adds_nothing(hook, tmp_path) -> None:
    for target, version in (("wheel", "editable"), ("sdist", "standard"), ("sdist", "editable")):
        instance = object.__new__(hook.CustomBuildHook)
        instance.target_name = target
        instance.root = str(ROOT)
        build_data: dict = {"force_include": {}}
        instance.initialize(version, build_data)
        assert build_data["force_include"] == {}
        assert instance._folder is None
    assert _fingerprint() == _fingerprint()


def test_the_hook_leaves_the_imported_modules_alone(hook, tmp_path) -> None:
    """A hook run in a process that already imported skye must not drop the modules of skye."""
    import sys

    before = {name: module for name, module in sys.modules.items() if name.startswith("skye")}
    hook.make_copies(SRC, tmp_path)
    assert all(sys.modules.get(name) is module for name, module in before.items())


def test_a_wheel_build_forces_the_copies_and_cleans_its_folder(hook) -> None:
    instance = object.__new__(hook.CustomBuildHook)
    instance.target_name = "wheel"
    instance.root = str(ROOT)
    build_data: dict = {"force_include": {}}
    instance.initialize("standard", build_data)
    folder = Path(instance._folder)
    try:
        forced = build_data["force_include"]
        assert len(forced) > 100
        assert all(Path(path).is_relative_to(folder) for path in forced)
        assert all(target.startswith("skye/") for target in forced.values())
    finally:
        instance.finalize("standard", build_data, "ignored")
    assert not folder.exists()


PYTHON_SAMPLE = "".join(
    [
        "#!/usr/bin/env python\n",
        "# -*- coding: utf-8 -*-\n",
        '"""A docstring with # a hash."""\n',
        "\n",
        'value = "a # not a comment"  # a comment\n',
        'text = f"{value} # still text"\n',
        "# a comment alone\n",
        "\n",
        "\n",
        "def f(x):  # trailing\n",
        '    """Another # docstring."""\n',
        "    return x + \\\n",
        "        1\n",
    ]
)


def test_strip_python_cuts_only_comments(hook) -> None:
    result = hook.strip_python(PYTHON_SAMPLE)
    assert result.startswith("#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n")
    assert 'value = "a # not a comment"\n' in result
    assert 'text = f"{value} # still text"\n' in result
    assert '"""A docstring with # a hash."""' in result
    assert '"""Another # docstring."""' in result
    assert "def f(x):\n" in result
    assert "a comment" not in result.replace("not a comment", "")
    assert result.count("\n") == PYTHON_SAMPLE.count("\n")
    assert ast.dump(ast.parse(result)) == ast.dump(ast.parse(PYTHON_SAMPLE))


def test_strip_python_keeps_the_line_endings_it_was_given(hook) -> None:
    source = "x = 1  # one\r\n# two\r\ny = 2\r\n"
    assert hook.strip_python(source) == "x = 1\r\n\r\ny = 2\r\n"


def test_strip_python_keeps_a_file_that_cannot_be_tokenized(hook, capsys) -> None:
    broken = "def f(:\n    # nothing\n"
    assert hook.strip_python(broken, "broken.py") == broken
    assert "broken.py" in capsys.readouterr().err


SKYE_SAMPLE = "".join(
    [
        "---\n",
        'title = "t" # not a comment: the front matter stays as it is\n',
        'version = "1.0"\n',
        "---\n",
        "/**\n",
        " * Example:\n",
        " *   a block\n",
        " **/\n",
        "# a line\n",
        'prompt "p" {\n',
        "  variables = { a = string }   # trailing\n",
        '  message "system" { text = "a /* b */ # c" }  /* inline */\n',
        "}\n",
    ]
)


def test_strip_skye_cuts_comments_and_keeps_strings_and_front_matter(hook) -> None:
    from skye.base.dsl.lexer import tokenize

    result = hook.strip_skye(SKYE_SAMPLE, tokenize)
    assert result.startswith('---\ntitle = "t" # not a comment: the front matter stays as it is\n')
    assert '"a /* b */ # c"' in result
    for gone in ("Example", "a block", "a line", "trailing", "inline"):
        assert gone not in result
    assert result.count("\n") == SKYE_SAMPLE.count("\n")
    assert build(result) == build(SKYE_SAMPLE)


def test_strip_skye_keeps_a_text_the_lexer_rejects(hook, capsys) -> None:
    from skye.base.dsl.lexer import tokenize

    broken = 'prompt "p" { /* never closed\n'
    assert hook.strip_skye(broken, tokenize, "broken.skye") == broken
    assert "broken.skye" in capsys.readouterr().err


def test_the_size_gain_is_reported(built, capsys) -> None:
    entries = _entries(built["wheel"])
    before = after = 0
    for name, data in entries.items():
        if name.endswith((".py", ".skye")):
            before += (ROOT / "src" / name).stat().st_size
            after += len(data)
    measure.report(f"| wheel without comments | {before / 1024:.0f} KB -> {after / 1024:.0f} KB |")
    with capsys.disabled():
        print(f"\nPython and template files: {before} bytes -> {after} bytes (-{before - after})")
    assert after <= before
