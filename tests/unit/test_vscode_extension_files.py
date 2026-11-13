"""The VS Code extension shipped in ``skye/utils/vscode_extension`` is well formed.

The folder is packed into a ``.vsix`` by ``skye vscode install``; these tests check the files
against the contract the installer and the ``skye check --format json`` command rely on.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import skye
from skye.base.dsl import TEMPLATES, parse, skeleton
from skye.base.dsl.tree import Block

ROOT = Path(skye.__file__).parent / "utils" / "vscode_extension"
REPO = Path(__file__).resolve().parents[2]
GRAMMAR = ROOT / "syntaxes" / "skye.tmLanguage.json"

FILES = (
    "package.json",
    "extension.js",
    "language-configuration.json",
    "syntaxes/skye.tmLanguage.json",
    "README.md",
    "LICENSE.txt",
)

# Constructs that Oniguruma (the regex engine of TextMate grammars) knows and Python's ``re``
# does not: named groups without ``P``, \h \H \A-style escapes Python lacks, possessive and
# atomic groups (atomic is 3.11+ but kept here for safety), \G, \k<name>, \p{...}, conditionals.
_ONIGURUMA_ONLY = re.compile(
    r"\(\?<[A-Za-z]|\\[hHGKRXyYO]|\\k<|\\p\{|\\P\{|[*+?}]\+|\(\?>|\(\?\(|\(\?~"
)


def _load(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _regexes(node: Any) -> Iterator[tuple[str, str]]:
    """Every ``match``, ``begin``, ``end`` and ``while`` regex of a grammar, with its key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("match", "begin", "end", "while") and isinstance(value, str):
                yield key, value
            else:
                yield from _regexes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _regexes(item)


def _block_kinds(blocks: list[Block]) -> set[str]:
    kinds: set[str] = set()
    for block in blocks:
        kinds.add(block.kind)
        kinds |= _block_kinds([b for b in block.body if isinstance(b, Block)])
    return kinds


def _known_block_kinds() -> set[str]:
    """The block kinds ``skye.base.dsl`` knows, read by its own parser.

    Sources: every skeleton of ``skye new``, every ``skye`` example of the language guide and the
    ``.skye`` files of ``examples/``, plus the top-level kinds of the guide's table.
    """
    texts = [skeleton(kind, template=t) for kind, names in TEMPLATES.items() for t in names]
    guide = (REPO / "docs" / "reference" / "skye-language.md").read_text(encoding="utf-8")
    texts += re.findall(r"```skye\n(.*?)```", guide, flags=re.DOTALL)
    texts += [p.read_text(encoding="utf-8") for p in (REPO / "examples").rglob("*.skye")]
    kinds: set[str] = set()
    for text in texts:
        kinds |= _block_kinds(parse(text, "example.skye").blocks)
    table = guide.split("## Block kinds", 1)[1].split("###", 1)[0]
    kinds |= set(re.findall(r"^\| `([a-z_]+)", table, flags=re.MULTILINE))
    kinds -= {"include", "from", "import", "use", "override"}  # statements with their own rules, tested apart
    return kinds


def test_every_file_of_the_contract_exists() -> None:
    for name in FILES:
        assert (ROOT / name).is_file(), name


def test_package_json_matches_the_contract() -> None:
    package = _load("package.json")
    assert package["name"] == "skye"
    assert package["publisher"] == "skyeai"
    assert package["displayName"] == "Skye (.skye language)"
    assert package["version"] == "0.0.0"
    assert package["license"] == "MIT"
    assert package["engines"] == {"vscode": "^1.75.0"}
    assert package["main"] == "./extension.js"
    assert package["activationEvents"] == ["onLanguage:skye"]
    assert package["categories"] == ["Programming Languages", "Linters", "Formatters"]
    for key in ("dependencies", "devDependencies", "scripts"):
        assert key not in package, key

    contributes = package["contributes"]
    (language,) = contributes["languages"]
    assert language["id"] == "skye"
    assert language["extensions"] == [".skye"]
    assert language["aliases"] == ["Skye", "skye"]
    assert (ROOT / language["configuration"]).is_file()
    (grammar,) = contributes["grammars"]
    assert grammar["language"] == "skye"
    assert grammar["scopeName"] == "source.skye"
    assert (ROOT / grammar["path"]).resolve() == GRAMMAR.resolve()
    assert [c["command"] for c in contributes["commands"]] == ["skye.check"]

    props = contributes["configuration"]["properties"]
    assert props["skye.command"]["type"] == "array"
    assert props["skye.command"]["default"] == ["skye"]
    assert props["skye.run"]["enum"] == ["onType", "onSave"]
    assert props["skye.run"]["default"] == "onType"
    assert props["skye.registry"]["type"] == "array"
    assert props["skye.registry"]["default"] == []


def test_language_configuration_is_valid() -> None:
    config = _load("language-configuration.json")
    assert config["comments"]["lineComment"] == "#"
    assert ["{", "}"] in config["brackets"]
    assert {"open": '"', "close": '"', "notIn": ["string", "comment"]} in config["autoClosingPairs"]
    for key in ("increaseIndentPattern", "decreaseIndentPattern"):
        re.compile(config["indentationRules"][key])


def test_license_is_the_repository_license() -> None:
    assert (ROOT / "LICENSE.txt").read_text(encoding="utf-8") == (REPO / "LICENSE").read_text(
        encoding="utf-8"
    )


def test_grammar_is_valid_and_its_regexes_compile() -> None:
    grammar = json.loads(GRAMMAR.read_text(encoding="utf-8"))
    assert grammar["scopeName"] == "source.skye"
    regexes = list(_regexes(grammar))
    assert len(regexes) > 20
    compiled = 0
    for key, pattern in regexes:
        if _ONIGURUMA_ONLY.search(pattern):
            continue  # Oniguruma-only syntax: Python cannot judge it
        re.compile(pattern)
        compiled += 1
    assert compiled > 20


def _keywords() -> set[str]:
    grammar = json.loads(GRAMMAR.read_text(encoding="utf-8"))
    match = grammar["repository"]["block-keyword"]["match"]
    group = re.search(r"\(\?:([a-z_|]+)\)", match)
    assert group is not None
    return set(group.group(1).split("|"))


def test_grammar_keywords_cover_every_block_kind() -> None:
    known = _known_block_kinds()
    # The kinds the parser and builder dispatch on today; the reading above must find them all.
    assert {"router", "flow", "prompt", "route", "target", "step", "parallel", "choice"} <= known
    assert {"context", "message", "placeholder", "each", "when", "else"} <= known
    known.add("output")  # prompt output block: output "json" { schema = ... }
    missing = known - _keywords()
    assert not missing, f"block kinds missing from the grammar: {sorted(missing)}"


def test_extension_js_spawns_the_contract_command() -> None:
    source = (ROOT / "extension.js").read_text(encoding="utf-8")
    assert '"check", "--format", "json", "--stdin-filename"' in source
    assert '"-"' in source
    assert '"--registry"' in source
    assert "childProcess.spawn(" in source
    assert "shell: false" in source
    assert '"skye.check"' in source
    assert 'require("vscode")' in source
    assert len(source.splitlines()) <= 260  # check + format, still one small file
    assert '"fmt", "--stdin-filename", document.fileName, "-"' in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_extension_js_is_valid_javascript() -> None:
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(ROOT / "extension.js")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_grammar_has_the_include_words_in_their_positions() -> None:
    grammar = json.loads(GRAMMAR.read_text(encoding="utf-8"))
    repository = grammar["repository"]
    assert {"include-statement", "import-statement", "as-statement", "use-statement"} <= set(repository)
    patterns = {p["include"] for p in grammar["patterns"] if "include" in p}
    assert {"#include-statement", "#import-statement", "#as-statement", "#use-statement"} <= patterns
    # the words are positional: a variable called `use` or `from` in an assignment is not a keyword
    use = re.compile(repository["use-statement"]["match"])
    assert use.search("    use tools") and use.search("use memory  # the entries")
    assert not use.search("  use = 1") and not use.search("x = use")
    # `override` is a keyword only before a variables entry and before `when`
    override = re.compile(repository["override-statement"]["match"])
    assert override.search("    override show_ids = bool(true)") and override.search("  override when not show_ids {")
    assert not override.search("  override = string(\"\")") and not override.search("x = override")
    assert "#override-statement" in patterns
    start = re.compile(repository["import-statement"]["match"])
    assert start.search('from "lib/agent.skye" import tools') and not start.search("from = 1")
    assert re.compile(repository["include-statement"]["match"]).search('include "lib/m.skye" as m')


def test_extension_js_shows_a_mistake_of_a_partial_at_its_use_site() -> None:
    source = (ROOT / "extension.js").read_text(encoding="utf-8")
    assert "item.via" in source and "document.fileName" in source
