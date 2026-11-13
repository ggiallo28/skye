"""What belongs to the store stays in the store (Requirement 60.12, decisions D95 to D98).

Two static (AST) rules over ``src/skye`` outside ``store``, and over the tests outside
``tests/unit/store``:

1. No file imports a concrete backend class (``InMemoryBackend``, ``RedisBackend``, ...). A
   component gets a store with ``skye.store.backend(name)`` and tests it with ``check_backend``;
   which class stands behind a name is the business of ``store``. The classes are not listed here:
   they are the classes of ``store/plugins/*/backend.py`` that extend ``StorageBackend``, so a new
   backend is covered when it is written.
2. No file reads the key ``"count"`` of a stored value. How a counter is kept is the business of
   ``store``; the Port has ``count(key)`` for it (Requirement 60.9).

The count rule is narrow on purpose, to avoid false positives on unrelated dicts. It flags
``x["count"]`` and ``x.get("count")`` where ``x`` is the result of a ``.get(...)`` called on
something whose name says it is a store (a name or an attribute that contains ``storage``, ``store``
or ``backend``), directly or through one name assigned in the same function. It does not follow a
value through a call, a return or an attribute, and it does not know a store that has another name.

``KNOWN_IMPORTS`` lists the files outside the store that import a class today, each with the reason.
An entry only goes away: the test fails when a listed file no longer needs it. ``KNOWN_COUNT_READS``
is empty and must stay empty.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from tests.budget.measure import ROOT

SRC = ROOT / "src" / "skye"
STORE = SRC / "store"
TESTS = ROOT / "tests"
STORE_TESTS = TESTS / "unit" / "store"

#: Files outside the store that import a backend class, with the reason. The list only shrinks.
KNOWN_IMPORTS: dict[str, str] = {
    "tests/unit/plugins/test_store_view.py": "needs a class to register",
    "tests/unit/router/test_retry_policy.py": "double that counts calls",
    "tests/unit/router/test_review_fixes.py": "double that interleaves calls",
    "tests/unit/router/test_router_exports.py": "checks the store",
    "tests/unit/router/test_router_in_loop.py": "strict double",
}
#: Files that read the key "count" of a stored value outside the store. Stays empty (60.9).
KNOWN_COUNT_READS: dict[str, str] = {}

STORE_WORDS = ("storage", "store", "backend")


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def concrete_backends() -> frozenset[str]:
    """The classes of ``store/plugins/*/backend.py`` that extend ``StorageBackend``."""
    found: set[str] = set()
    for path in sorted((STORE / "plugins").glob("*/backend.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(
                _name(base) == "StorageBackend" for base in node.bases
            ):
                found.add(node.name)
    return frozenset(found)


def import_violations(source: str, concrete: frozenset[str]) -> list[tuple[int, str]]:
    """The lines of ``source`` that import a concrete backend class from the store."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        in_store = (
            module == "skye.store"
            or module.startswith("skye.store.")
            or (node.level > 0 and module.startswith("store"))
        )
        if not in_store:
            continue
        for alias in node.names:
            if alias.name in concrete:
                found.append((node.lineno, f"imports the backend class {alias.name} from {module}"))
    return found


def _is_store_get(node: ast.AST) -> bool:
    """``<store>.get(...)``, awaited or not, where the receiver is named like a store."""
    if isinstance(node, ast.Await):
        node = node.value
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    ):
        return False
    receiver = _name(node.func.value).lower()
    return any(word in receiver for word in STORE_WORDS)


def _from_store(value: ast.AST) -> bool:
    """The value is, or may be through ``or`` or ``if else``, the result of ``<store>.get(...)``."""
    if _is_store_get(value):
        return True
    if isinstance(value, ast.BoolOp):
        return any(_from_store(v) for v in value.values)
    if isinstance(value, ast.IfExp):
        return _from_store(value.body) or _from_store(value.orelse)
    return False


def _count_reads_in(scope: ast.AST) -> list[tuple[int, str]]:
    tainted: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and _from_store(node.value):
            tainted.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _from_store(node.value):
            if isinstance(node.target, ast.Name):
                tainted.add(node.target.id)
    found: list[tuple[int, str]] = []

    def stored(value: ast.AST) -> bool:
        return (isinstance(value, ast.Name) and value.id in tainted) or _from_store(value)

    for node in ast.walk(scope):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "count"
        ):
            if stored(node.value):
                found.append((node.lineno, 'reads the key "count" of a stored value'))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
        ):
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "count"
            ):
                if stored(node.func.value):
                    found.append((node.lineno, 'reads the key "count" of a stored value'))
    return found


def count_violations(source: str) -> list[tuple[int, str]]:
    """The lines of ``source`` that read the key ``"count"`` of a value that comes from a store."""
    tree = ast.parse(source)
    scopes: list[ast.AST] = [tree]
    scopes += [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    seen: dict[int, tuple[int, str]] = {}
    for scope in scopes:
        for line, message in _count_reads_in(scope):
            seen[line] = (line, message)
    return sorted(seen.values())


def _files() -> Iterator[Path]:
    for root in (SRC, TESTS):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or STORE in path.parents or STORE_TESTS in path.parents:
                continue
            yield path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _scan(check) -> dict[str, list[tuple[int, str]]]:
    result: dict[str, list[tuple[int, str]]] = {}
    for path in _files():
        found = check(path.read_text(encoding="utf-8"))
        if found:
            result[_rel(path)] = found
    return result


def _describe(result: dict[str, list[tuple[int, str]]]) -> str:
    return "\n".join(
        f"  {path}:{line} {message}"
        for path, found in sorted(result.items())
        for line, message in found
    )


def test_the_backend_classes_are_found():
    concrete = concrete_backends()
    expected = {
        "InMemoryBackend",
        "FileSystemBackend",
        "DynamoDBBackend",
        "RedisBackend",
        "PostgreSQLBackend",
        "DurableFunctionBackend",
    }
    assert (
        expected <= concrete
    ), f"missing from store/plugins/*/backend.py: {sorted(expected - concrete)}"


def test_no_backend_class_is_imported_outside_the_store():
    concrete = concrete_backends()
    result = _scan(lambda source: import_violations(source, concrete))
    new = {path: found for path, found in result.items() if path not in KNOWN_IMPORTS}
    assert not new, (
        "a backend class is imported outside the store (use skye.store.backend(name)):\n"
        + _describe(new)
    )


def test_the_known_imports_are_still_needed():
    concrete = concrete_backends()
    result = _scan(lambda source: import_violations(source, concrete))
    stale = sorted(path for path in KNOWN_IMPORTS if path not in result)
    assert (
        not stale
    ), f"these files no longer import a backend class, remove them from KNOWN_IMPORTS: {stale}"


def test_no_stored_count_is_read_outside_the_store():
    result = _scan(count_violations)
    new = {path: found for path, found in result.items() if path not in KNOWN_COUNT_READS}
    assert not new, (
        'the key "count" of a stored value is read outside the store (use CounterStore.count):\n'
        + _describe(new)
    )


def test_the_known_count_reads_are_still_needed():
    result = _scan(count_violations)
    stale = sorted(path for path in KNOWN_COUNT_READS if path not in result)
    assert (
        not stale
    ), f"these files no longer read a stored count, remove them from KNOWN_COUNT_READS: {stale}"


# The scanner itself: a rule that stops finding things would pass for the wrong reason.
CONCRETE = frozenset({"InMemoryBackend", "RedisBackend"})


def test_the_scanner_reports_a_concrete_import():
    source = (
        "from skye.store.plugins.memory import InMemoryBackend\n"
        "from skye.store import RedisBackend as R\n"
    )
    assert [line for line, _ in import_violations(source, CONCRETE)] == [1, 2]


def test_the_scanner_leaves_the_allowed_imports_alone():
    source = (
        "from skye.store import backend, check_backend, FakeClock\n"
        "from other import InMemoryBackend\n"
    )
    assert import_violations(source, CONCRETE) == []


def test_the_scanner_reports_a_stored_count_read():
    source = (
        "async def f(self):\n"
        "    data = await self.storage.get('k') or {}\n"
        "    a = data['count']\n"
        "    b = data.get('count', 0)\n"
        "    c = (await self.backend.get('k'))['count']\n"
    )
    assert [line for line, _ in count_violations(source)] == [3, 4, 5]


def test_the_scanner_leaves_other_dicts_alone():
    source = (
        "def f(settings, storage):\n"
        "    a = {'count': 1}['count']\n"
        "    b = settings.get('count')\n"
        "    data = settings.get('other')\n"
        "    c = data['count']\n"
        "    n = storage.count('k')\n"
    )
    assert count_violations(source) == []
