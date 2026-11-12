"""Extras declare exactly what their Component imports, and `import skye` stays clean.

Task 1.3 of .kiro/specs/0-base-structure. No network, no install; a few subprocesses.

* Extras: for each Extra in pyproject.toml, the third-party libraries declared must be the
  third-party libraries the Component's code imports (module level, lazy, or through
  LazyImporter), core dependencies excluded. Missing and unused declarations are reported.
  The [imports.max_files] list in budgets.toml is cross-checked against the same data.
* Footprint: a fresh `import skye` in a subprocess follows [load] in budgets.toml. Module
  count and time are measured here, with the development libraries installed, so the limits
  are the same as the clean-environment ones in test_footprint_budget.py (which stays the
  authority for core-only installs).

Known failures of the current tree are xfail with a reason; budgets.toml is never loosened.
"""

from __future__ import annotations

import ast
import sys

import pytest

from tests.budget.measure import (
    ROOT,
    load_budgets,
    load_metrics,
    normalize,
    pyproject,
    requirement_name,
)

SRC = ROOT / "src" / "skye"
BUDGETS = load_budgets()

# Extra -> files or directories (relative to src/skye) forming its Component. Current layout;
# update when the structure moves.
EXTRA_PATHS: dict[str, list[str]] = {
    # auth: authentication and credentials (Layer 0). `rsa` is declared for RS256 signing
    # (`auth/rsa_signing.py`); the SigV4 signer and the other strategies are standard library.
    "auth": ["auth"],
    "openai": ["models/utilities/openai_compatible", "models/plugins/openai", "models/plugins/azure"],
    # tokens: exact token counting (`tiktoken`, lazy and optional; D33).
    "tokens": ["models/token_counter.py"],
    "anthropic": ["models/utilities/anthropic_compatible", "models/plugins/anthropic"],
    "bedrock": ["models/plugins/bedrock"],
    "google": ["models/plugins/google"],
    "cohere": ["models/plugins/cohere"],
    # tools carries no third-party library (known_empty). fastmcp, the optional MCP substitute,
    # belongs to the separate `mcp` extra (Requirement 15).
    "tools": [
        "tools/__init__.py",
        "tools/capability_call_handler.py",
        "tools/capability_models.py",
        "tools/decorator.py",
        "tools/exceptions.py",
        "tools/local_function.py",
        "tools/mcp_boundary.py",
        "tools/mcp_client.py",
        "tools/mcp_resource.py",
        "tools/registry.py",
        "tools/remote_api.py",
        "tools/plugins/__init__.py",
        "tools/plugins/skyemcp",
    ],
    "mcp": [
        "tools/plugins/fastmcp",
    ],
    # Store backends: one extra per backend (D99). The drivers are imported lazily through `missing_extra`, which names
    # the extra, so `store/plugins/postgres/backend.py` (three drivers) and `store/plugins/redis/backend.py` (two) are attributed by those hints, not by its path.
    "memory": ["memory"],
    "redis": [],
    "valkey": [],
    "postgres": [],
    "postgres-asyncpg": [],
    "aws": [],
    "observe": ["observe"],
}

# Distribution name -> top-level import names (when they differ from the name).
IMPORT_NAMES: dict[str, set[str]] = {
    "azure-ai-inference": {"azure"},
    "azure-identity": {"azure"},
    "google-cloud-aiplatform": {"google"},
    "opentelemetry-api": {"opentelemetry"},
    "prometheus-client": {"prometheus_client"},
    "psycopg2-binary": {"psycopg2"},
    "asyncpg": {"asyncpg"},
    "fastmcp": {"fastmcp"},
    "fastmcp-slim": {"fastmcp"},
    }

# Libraries that stay out of the comparison: the standard library and Skye itself.
CORE_IMPORTS = {"skye"} | set(sys.stdlib_module_names)


def _import_names(dist: str) -> set[str]:
    dist = normalize(dist)
    return IMPORT_NAMES.get(dist, {dist.replace("-", "_")})


def _core_imports() -> set[str]:
    names: set[str] = set()
    for req in pyproject()["project"]["dependencies"]:
        names |= _import_names(requirement_name(req))
    return names


def _files(entries: list[str]):
    for entry in entries:
        path = SRC / entry
        yield from sorted(path.rglob("*.py")) if path.is_dir() else [path]


def _scan(path) -> list[tuple[str, str | None]]:
    """(top-level library, extra named at the call site or None) for every import in a file.

    Counts imports anywhere (module level, inside functions, TYPE_CHECKING excluded) and
    string-literal LazyImporter.import_module("lib", install_extra="extra") and missing_extra("lib", extra="extra") calls.
    """
    found: list[tuple[str, str | None]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skipped: set[int] = set()
    for node in ast.walk(tree):
        test = getattr(node, "test", None)
        if isinstance(node, ast.If) and (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        ):
            skipped |= {id(n) for b in node.body for n in ast.walk(b)}
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Import):
            found += [(a.name.split(".")[0], None) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.module.split(".")[0], None))
        elif (
            isinstance(node, ast.Call)
            and (
                getattr(node.func, "attr", None) == "import_module"
                or getattr(node.func, "id", getattr(node.func, "attr", None)) == "missing_extra"
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            extra = next(
                (k.value.value for k in node.keywords
                 if k.arg in ("install_extra", "extra") and isinstance(k.value, ast.Constant)),
                None,
            )
            found.append((node.args[0].value.split(".")[0], extra))
    return [(lib, extra) for lib, extra in found if lib not in CORE_IMPORTS | _core_imports()]


def _code_libraries() -> dict[str, dict[str, set[str]]]:
    """extra -> {library: files}. A LazyImporter call naming its install_extra counts for that extra."""
    out: dict[str, dict[str, set[str]]] = {e: {} for e in EXTRA_PATHS}
    preinstalled = {n for d in BUDGETS["lambda"]["preinstalled"] for n in _import_names(d)}
    for extra, entries in EXTRA_PATHS.items():
        for file in _files(entries):
            for lib, hint in _scan(file):
                if hint is None:
                    out[extra].setdefault(lib, set()).add(str(file.relative_to(SRC)))
    for file in sorted(SRC.rglob("*.py")):
        for lib, hint in _scan(file):
            if hint in out:
                out[hint].setdefault(lib, set()).add(str(file.relative_to(SRC)))
    # Lambda libraries are free for everyone, but an extra that declares one still owns it.
    declared = _declared()
    for extra, libs in out.items():
        for lib in [l for l in libs if l in preinstalled and l not in declared.get(extra, set())]:
            del libs[lib]
    return out


def _declared() -> dict[str, set[str]]:
    core = _core_imports()
    extras = pyproject()["project"]["optional-dependencies"]
    return {
        extra: set().union(*[_import_names(requirement_name(r)) for r in extras[extra]]) - core
        for extra in EXTRA_PATHS
    }


# Reasons the current tree does not satisfy the declare-exactly rule yet: none. The `auth` extra declares exactly `rsa`,
# which the RS256 minting (`auth/rsa_signing.py`) imports lazily through `missing_extra`.
EXTRA_XFAIL: dict[str, str] = {}


@pytest.mark.parametrize("extra", sorted(EXTRA_PATHS))
def test_extra_declares_exactly_what_its_component_imports(extra: str, request: pytest.FixtureRequest) -> None:
    if extra in EXTRA_XFAIL:
        request.applymarker(pytest.mark.xfail(reason=EXTRA_XFAIL[extra], strict=True))
    used = set(_code_libraries()[extra])
    declared = _declared()[extra]
    missing = sorted(used - declared)
    unused = sorted(declared - used)
    assert not missing and not unused, (
        f"extra '{extra}': imported but not declared {missing}; declared but never imported {unused}. "
        "Declare the library in pyproject.toml or remove the dead declaration."
    )


def test_auth_extra_declares_exactly_rsa() -> None:
    """Requirement 18: the auth extra declares only `rsa`; the google extra does not declare it."""
    extras = pyproject()["project"]["optional-dependencies"]
    assert {requirement_name(r) for r in extras["auth"]} == {"rsa"}
    assert "rsa" not in {requirement_name(r) for r in extras["google"]}


def test_every_extra_with_a_component_is_checked() -> None:
    extras = set(pyproject()["project"]["optional-dependencies"])
    policy = BUDGETS["extras_policy"]
    unchecked = extras - set(EXTRA_PATHS) - set(policy["known_empty"]) - set(policy["bundles"])
    assert not unchecked, f"Extras with no component mapping in EXTRA_PATHS: {sorted(unchecked)}"


def test_every_third_party_import_belongs_to_an_extra_or_core() -> None:
    """Counterpart of [imports.max_files]: no library imported by src/skye is unowned."""
    owned = {lib for libs in _code_libraries().values() for lib in libs}
    preinstalled = {n for d in BUDGETS["lambda"]["preinstalled"] for n in _import_names(d)}
    mapped = {str(f.relative_to(SRC)) for f in _files([p for ps in EXTRA_PATHS.values() for p in ps])}
    stray: dict[str, list[str]] = {}
    for file in sorted(SRC.rglob("*.py")):
        rel = str(file.relative_to(SRC))
        for lib, hint in _scan(file):
            if rel not in mapped and hint is None and lib not in owned and lib not in preinstalled:
                stray.setdefault(lib, []).append(rel)
    assert not stray, f"Third-party libraries imported outside any extra's component: {stray}"


def test_listed_module_level_imports_are_declared_by_an_extra() -> None:
    """Every library in [imports.max_files] is a core dependency or declared by some extra."""
    core = _core_imports()
    declared = set().union(*_declared().values())
    undeclared = sorted(set(BUDGETS["imports"]["max_files"]) - core - declared)
    assert not undeclared, f"[imports.max_files] lists libraries no extra declares: {undeclared}"


# --- clean import / footprint -------------------------------------------------------------

LOAD = BUDGETS["load"]


@pytest.fixture(scope="module")
def fresh_import() -> dict:
    return load_metrics(sys.executable, runs=3)


def test_import_loads_nothing_forbidden(fresh_import: dict) -> None:
    forbidden, known = set(LOAD["forbidden_at_import"]), set(LOAD["known_leaks"])
    leaked = sorted((forbidden & set(fresh_import["loaded"])) - known)
    assert not leaked, f"`import skye` imports {leaked}; keep optional libraries behind a lazy import."


def test_import_has_no_known_leak(fresh_import: dict) -> None:
    """known_leaks is empty; test_known_leaks_are_current keeps it honest if an entry is ever added."""
    assert not set(LOAD["known_leaks"]) & set(fresh_import["loaded"])


def test_known_leaks_are_current(fresh_import: dict) -> None:
    import importlib.util

    installed = {k for k in LOAD["known_leaks"] if importlib.util.find_spec(k)}
    fixed = sorted(installed - set(fresh_import["loaded"]))
    assert not fixed, f"`import skye` no longer imports {fixed}: remove them from known_leaks in budgets.toml."


def test_import_stays_within_module_budget(fresh_import: dict) -> None:
    assert fresh_import["modules"] <= LOAD["max_modules_loaded"], f"`import skye` loads {fresh_import['modules']} modules"


def test_import_stays_within_time_budget(fresh_import: dict) -> None:
    assert fresh_import["ms"] <= LOAD["max_import_ms"], f"`import skye` takes {fresh_import['ms']:.0f} ms"


def test_known_import_failures_are_current() -> None:
    """Subpackages in known_import_failures must still fail on a core-only install.

    Here the development libraries are installed, so instead check the cause statically: a
    listed module must import a third-party library at module level that no core dependency covers.
    """
    from tests.budget.measure import module_level_third_party_imports

    core = _core_imports()
    found = module_level_third_party_imports(BUDGETS["lambda"]["preinstalled"])
    for module in BUDGETS["core"]["known_import_failures"]:
        pkg_dir = module.replace(".", "/")
        files = [f for fs in found.values() for f in fs if f.startswith(pkg_dir + "/")]
        offenders = {lib for lib, fs in found.items() if lib not in core and any(f.startswith(pkg_dir + "/") for f in fs)}
        assert files and offenders, (
            f"{module} no longer imports a non-core library at module level; remove it from "
            "known_import_failures in budgets.toml."
        )
